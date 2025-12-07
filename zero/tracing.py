"""
OpenTelemetry trace collection for Zero.

Provides a simple HTTP server to capture OTEL logs from Codex execution.
Note: Codex exports OTLP logs (not traces), so we need a log-capable receiver.
"""

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


# Embedded Python collector script - receives OTLP HTTP logs
COLLECTOR_SCRIPT = '''
import http.server
import json
import sys
from datetime import datetime

class OTLPLogCollector(http.server.BaseHTTPRequestHandler):
    """OTLP HTTP log receiver that decodes protobuf and writes structured JSONL."""
    output_file = None
    verbose = False
    
    def log_message(self, format, *args):
        if self.verbose:
            sys.stderr.write(f"[OTEL] {format % args}\\n")
    
    def _decode_protobuf(self, body):
        """Decode OTLP protobuf logs into structured JSON."""
        try:
            from opentelemetry.proto.logs.v1.logs_pb2 import LogsData
            
            logs_data = LogsData()
            logs_data.ParseFromString(body)
            
            # Convert protobuf to dict
            result = {
                "resource_logs": []
            }
            
            for resource_log in logs_data.resource_logs:
                resource_dict = {
                    "resource": {},
                    "scope_logs": []
                }
                
                # Extract resource attributes
                if resource_log.resource:
                    resource_dict["resource"]["attributes"] = {}
                    for attr in resource_log.resource.attributes:
                        resource_dict["resource"]["attributes"][attr.key] = self._extract_value(attr.value)
                
                # Extract scope logs
                for scope_log in resource_log.scope_logs:
                    scope_dict = {
                        "scope": {},
                        "log_records": []
                    }
                    
                    if scope_log.scope:
                        scope_dict["scope"]["name"] = scope_log.scope.name
                        scope_dict["scope"]["version"] = scope_log.scope.version
                    
                    # Extract log records
                    for log_record in scope_log.log_records:
                        record = {
                            "time_unix_nano": str(log_record.time_unix_nano),
                            "severity_number": log_record.severity_number,
                            "severity_text": log_record.severity_text,
                            "body": self._extract_value(log_record.body),
                            "attributes": {},
                            "trace_id": log_record.trace_id.hex() if log_record.trace_id else None,
                            "span_id": log_record.span_id.hex() if log_record.span_id else None,
                        }
                        
                        # Extract attributes (this is where reasoning data will be!)
                        for attr in log_record.attributes:
                            record["attributes"][attr.key] = self._extract_value(attr.value)
                        
                        scope_dict["log_records"].append(record)
                    
                    resource_dict["scope_logs"].append(scope_dict)
                
                result["resource_logs"].append(resource_dict)
            
            return result
            
        except ImportError:
            return {"error": "opentelemetry-proto not installed", "format": "protobuf"}
        except Exception as e:
            return {"error": f"Failed to decode protobuf: {str(e)}", "format": "protobuf"}
    
    def _extract_value(self, any_value):
        """Extract value from OTLP AnyValue."""
        if any_value.HasField("string_value"):
            return any_value.string_value
        elif any_value.HasField("bool_value"):
            return any_value.bool_value
        elif any_value.HasField("int_value"):
            return any_value.int_value
        elif any_value.HasField("double_value"):
            return any_value.double_value
        elif any_value.HasField("array_value"):
            return [self._extract_value(v) for v in any_value.array_value.values]
        elif any_value.HasField("kvlist_value"):
            return {kv.key: self._extract_value(kv.value) for kv in any_value.kvlist_value.values}
        elif any_value.HasField("bytes_value"):
            return any_value.bytes_value.hex()
        return None
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        content_type = self.headers.get('Content-Type', '')
        body = self.rfile.read(content_length)
        
        # Create record with metadata
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "path": self.path,
            "content_type": content_type,
            "content_length": len(body),
        }
        
        # Decode body based on content type
        if 'json' in content_type.lower():
            try:
                record["data"] = json.loads(body.decode('utf-8'))
            except Exception as e:
                record["body_raw"] = body.decode('utf-8', errors='replace')
                record["decode_error"] = str(e)
        elif 'protobuf' in content_type.lower() or 'binary' in content_type.lower() or 'octet' in content_type.lower():
            # Decode protobuf
            record["data"] = self._decode_protobuf(body)
            
            # Keep hex for debugging if decode failed
            if "error" in record["data"]:
                if len(body) > 2000:
                    record["body_hex_truncated"] = body[:2000].hex()
                else:
                    record["body_hex"] = body.hex()
        else:
            # Unknown format
            record["body_raw"] = body.decode('utf-8', errors='replace')[:1000]
        
        # Write to JSONL file
        try:
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(record) + '\\n')
                f.flush()
        except Exception as e:
            sys.stderr.write(f"[OTEL] Error writing to file: {e}\\n")
        
        # Log to stderr
        if self.verbose:
            msg = f"[OTEL] Received: {self.path} - {len(body)} bytes ({content_type})"
            if "data" in record and "resource_logs" in record["data"]:
                log_count = sum(
                    len(scope["log_records"]) 
                    for rl in record["data"]["resource_logs"] 
                    for scope in rl["scope_logs"]
                )
                msg += f" - {log_count} log records"
            sys.stderr.write(msg + "\\n")
        
        # Send success response (OTLP expects empty JSON or protobuf response)
        self.send_response(200)
        if 'protobuf' in content_type.lower() or 'binary' in content_type.lower():
            self.send_header('Content-Type', 'application/x-protobuf')
            self.end_headers()
            self.wfile.write(b'')
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{}')
    
    def do_GET(self):
        # Health check endpoint
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=str, required=True)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    
    OTLPLogCollector.output_file = args.output
    OTLPLogCollector.verbose = args.verbose
    
    sys.stderr.write(f"[OTEL] Log collector starting on port {args.port}\\n")
    sys.stderr.write(f"[OTEL] Output file: {args.output}\\n")
    sys.stderr.write(f"[OTEL] Endpoints: /v1/logs, /v1/traces\\n")
    sys.stderr.write(f"[OTEL] Protobuf decoding: enabled\\n")
    
    server = http.server.HTTPServer(('0.0.0.0', args.port), OTLPLogCollector)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write(f"[OTEL] Shutting down...\\n")
'''


class OtelTraceCollector:
    """Collects OTEL logs from Codex execution.

    Uses a simple Python HTTP server to capture OTLP log records
    and writes them to a JSONL file for analysis.

    Note: Codex exports OTLP logs (not traces), so we use a custom
    Python-based collector instead of otel-cli which only handles traces.

    Usage:
        collector = OtelTraceCollector(output_file="/tmp/traces.jsonl")
        collector.start()
        # ... run codex ...
        collector.stop()

    Or as a context manager:
        with OtelTraceCollector(output_file="/tmp/traces.jsonl") as collector:
            # ... run codex ...
    """

    def __init__(
        self,
        output_file: str | Path,
        host: str = "0.0.0.0",
        port: int = 4318,
        verbose: bool = False,
    ):
        """Initialize the trace collector.

        Args:
            output_file: Path to write JSONL logs
            host: Host to bind the server to
            port: Port to listen on (default: 4318 for OTLP HTTP)
            verbose: Enable verbose output
        """
        self.output_file = Path(output_file)
        self.host = host
        self.port = port
        self.verbose = verbose
        self._process: subprocess.Popen | None = None
        self._script_file: str | None = None
        self._started = False

    @staticmethod
    def is_available() -> bool:
        """Check if Python is available (always true since we're running Python)."""
        return True

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is already in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return False
            except OSError:
                return True

    def _kill_process_on_port(self, port: int) -> bool:
        """Try to kill any process using the specified port."""
        try:
            # Use lsof to find the process
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                        if self.verbose:
                            print(f"   Killed existing process {pid} on port {port}")
                    except (ProcessLookupError, ValueError):
                        pass
                time.sleep(0.5)  # Give time for port to be released
                return True
        except FileNotFoundError:
            # lsof not available
            pass
        return False

    def start(self) -> "OtelTraceCollector":
        """Start the collector server.

        Returns:
            self for chaining
        """
        if self._started:
            return self

        # Check if port is in use and try to kill existing process
        if self._is_port_in_use(self.port):
            if self.verbose:
                print(f"⚠️  Port {self.port} is in use, attempting to clean up...")
            if not self._kill_process_on_port(self.port):
                # If we couldn't kill it, check again
                if self._is_port_in_use(self.port):
                    raise RuntimeError(
                        f"Port {self.port} is already in use and could not be freed. "
                        f"Try: lsof -ti :{self.port} | xargs kill -9"
                    )

        # Ensure output directory exists
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write collector script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(COLLECTOR_SCRIPT)
            self._script_file = f.name

        if self.verbose:
            print(f"🔍 Starting OTEL log collector on port {self.port}")
            print(f"   Output: {self.output_file}")

        try:
            # Build command
            cmd = [
                sys.executable,
                self._script_file,
                "--port", str(self.port),
                "--output", str(self.output_file),
            ]
            if self.verbose:
                cmd.append("--verbose")

            # Start the collector server
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=sys.stderr if self.verbose else subprocess.DEVNULL,
                # Don't let it receive signals meant for the parent
                preexec_fn=os.setpgrp if hasattr(os, "setpgrp") else None,
            )

            # Give it a moment to start and bind to the port
            time.sleep(0.5)

            # Check if it started successfully
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"OTEL collector failed to start (exit code {self._process.returncode})"
                )

            self._started = True

            # Register cleanup on exit
            atexit.register(self.stop)

            if self.verbose:
                print(f"✅ OTEL log collector started (PID: {self._process.pid})")
                print(f"   Listening on: http://{self.host}:{self.port}")
                print(f"   Endpoints: /v1/logs, /v1/traces")

        except Exception as e:
            # Cleanup script file on error
            if self._script_file and os.path.exists(self._script_file):
                os.unlink(self._script_file)
            raise RuntimeError(f"Failed to start collector: {e}")

        return self

    def stop(self) -> None:
        """Stop the collector server gracefully."""
        if not self._started or self._process is None:
            return

        if self.verbose:
            print(f"🛑 Stopping OTEL log collector (PID: {self._process.pid})...")

        try:
            # Try graceful shutdown first
            self._process.terminate()

            try:
                # Wait up to 3 seconds for graceful shutdown
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't stop
                if self.verbose:
                    print("   Force killing collector...")
                self._process.kill()
                self._process.wait()

        except Exception as e:
            if self.verbose:
                print(f"   Warning: Error stopping collector: {e}")

        finally:
            # Cleanup script file
            if self._script_file and os.path.exists(self._script_file):
                try:
                    os.unlink(self._script_file)
                except:
                    pass

            self._process = None
            self._script_file = None
            self._started = False

            # Unregister atexit handler
            try:
                atexit.unregister(self.stop)
            except Exception:
                pass

            if self.verbose:
                print(f"✅ OTEL log collector stopped")
                print(f"   Logs written to: {self.output_file}")

    def is_running(self) -> bool:
        """Check if the collector is currently running."""
        if not self._started or self._process is None:
            return False
        return self._process.poll() is None

    def get_endpoint(self) -> str:
        """Get the OTLP endpoint URL."""
        return f"http://localhost:{self.port}"

    def get_logs_endpoint(self) -> str:
        """Get the logs endpoint URL (what Codex should use)."""
        return f"{self.get_endpoint()}/v1/logs"

    def __enter__(self) -> "OtelTraceCollector":
        """Context manager entry."""
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.stop()


def get_otel_environment(
    endpoint: str = "http://localhost:4318",
    service_name: str = "codex",
) -> dict[str, str]:
    """Get environment variables to configure OTEL export.

    Note: Codex uses config.toml for OTEL configuration, not environment
    variables. These are provided for compatibility with other tools.

    Args:
        endpoint: OTLP HTTP endpoint
        service_name: Service name for logs

    Returns:
        Dictionary of environment variables
    """
    return {
        # Standard OTEL environment variables (for other tools)
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_SERVICE_NAME": service_name,
    }
