"""
Codex CLI runner for Zero.

Handles the execution of Codex CLI with proper environment and configuration.
"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ZeroConfig
from .tracing import OtelTraceCollector


class CodexRunner:
    """Runs Codex CLI with the given configuration."""

    def __init__(self, config: ZeroConfig):
        """Initialize the runner with configuration."""
        self.config = config
        self._validate_codex_available()

    def _validate_codex_available(self) -> None:
        """Check if codex CLI is available."""
        if not shutil.which("codex"):
            raise RuntimeError(
                "codex CLI not found in PATH. Please install it:\n"
                "  npm install -g @openai/codex\n"
                "or\n"
                "  brew install codex\n"
                "See: https://github.com/openai/codex"
            )

    def _get_environment(self) -> dict[str, str]:
        """Build environment variables for codex execution."""
        env = os.environ.copy()

        # Set CODEX_HOME to our config directory
        config_dir = self.config.get_effective_config_dir()
        env["CODEX_HOME"] = config_dir

        # Set SESSION_ID for tracking
        env["SESSION_ID"] = self.config.session_id

        # Ensure API key environment variable is available
        if self.config.api_key_env:
            if self.config.api_key_env not in env:
                print(
                    f"Warning: API key environment variable {self.config.api_key_env} is not set",
                    file=sys.stderr,
                )

        return env

    def _build_command(self, query: str) -> list[str]:
        """Build the codex CLI command.
        
        - full_auto=True: uses `codex exec --full-auto` (non-interactive, auto-approve)
        - full_auto=False: uses `codex` TUI (interactive, asks for approval)
        """
        if self.config.full_auto:
            # Non-interactive execution mode
            cmd = ["codex", "exec", "--full-auto"]
        else:
            # Interactive TUI mode - will prompt for approval
            cmd = ["codex"]

        # Note: We don't use --skip-git-repo-check because setup_session_dir()
        # initializes the session directory as a git repo for Codex trust

        # Set writable roots via CLI config to session directory only
        session_path = str(Path(self.config.session_dir).resolve())
        cmd.extend(["--config", f'sandbox_workspace_write.writable_roots=["{session_path}"]'])

        # Set working directory to session directory (-C flag)
        cmd.extend(["-C", session_path])

        # Add the query (for TUI mode, this becomes the initial prompt)
        cmd.append(query)

        return cmd

    def _move_history_to_traces(self, codex_home: str) -> None:
        """Move history from CODEX_HOME to session traces directory.
        
        Copies persistence data and history files after Codex exits.
        """
        traces_dir = Path(self.config.session_dir) / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        
        codex_home_path = Path(codex_home)
        
        # Copy the persistence folder (created by persistence = "save-all")
        persistence_src = codex_home_path / "persistence"
        if persistence_src.exists():
            persistence_dest = traces_dir / "persistence"
            try:
                shutil.copytree(persistence_src, persistence_dest, dirs_exist_ok=True)
                if self.config.verbose:
                    print(f"📋 Copied persistence: {persistence_src} -> {persistence_dest}")
            except Exception as e:
                if self.config.verbose:
                    print(f"Warning: Failed to copy persistence: {e}")
        
        # Look for any history files in CODEX_HOME
        history_patterns = ["*.history", "history*", ".codex_history*", "*.sqlite", "*.db"]
        
        for pattern in history_patterns:
            for history_file in codex_home_path.glob(pattern):
                if history_file.is_file():
                    dest = traces_dir / f"codex_{history_file.name}"
                    try:
                        shutil.copy2(history_file, dest)
                        if self.config.verbose:
                            print(f"📋 Copied history: {history_file} -> {dest}")
                    except Exception as e:
                        if self.config.verbose:
                            print(f"Warning: Failed to copy history {history_file}: {e}")

    def run_session(self, dry_run: bool = False) -> int:
        """Run Codex for a session.

        Args:
            dry_run: If True, print command without executing

        Returns:
            Exit code from codex execution (0 = success)
        """
        # Setup session directory structure (optionally clean first)
        self.config.setup_session_dir(clean=self.config.clean)
        
        query = self.config.get_query()
        output_path = self.config.get_output_path()

        # Setup tracing if enabled
        traces_output_path = None
        collector = None
        if self.config.collect_traces:
            traces_output_path = self.config.get_traces_output_path()
            Path(traces_output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build command and environment
        cmd = self._build_command(query)
        env = self._get_environment()
        codex_home = env.get("CODEX_HOME", "")

        if self.config.verbose or dry_run:
            print(f"\n{'='*60}")
            print(f"Session Directory: {self.config.session_dir}")
            print(f"Session ID: {self.config.session_id}")
            print(f"Read-only Directories: {self.config.read_only_dirs}")
            print(f"Output: {output_path}")
            if traces_output_path:
                print(f"Traces: {traces_output_path}")
            print(f"{'='*60}")
            print(f"\nEnvironment:")
            print(f"  CODEX_HOME={codex_home}")
            print(f"  SESSION_ID={env.get('SESSION_ID', 'not set')}")
            if self.config.api_key_env:
                key_set = self.config.api_key_env in env
                print(f"  {self.config.api_key_env}={'[set]' if key_set else '[not set]'}")
            print(f"\nCommand:")
            print(f"  {shlex.join(cmd)}")
            print()

        if dry_run:
            print("[DRY RUN] Command not executed")
            if self.config.collect_traces:
                print(f"[DRY RUN] Would start OTEL log collector on port {self.config.otel_port}")
            return 0

        # Start trace collector if enabled
        if self.config.collect_traces:
            collector = OtelTraceCollector(
                output_file=traces_output_path,
                port=self.config.otel_port,
                verbose=self.config.verbose,
            )
            collector.start()

        # Run the command
        print(f"🚀 Running Zero agent...")
        
        # Setup stdout/stderr capture to traces directory
        stdout_log_path = str(Path(self.config.session_dir) / "traces" / "stdout.log")
        
        try:
            if self.config.full_auto:
                # Full-auto mode: capture stdout to log file while streaming to console
                with open(stdout_log_path, 'w') as log_file:
                    process = subprocess.Popen(
                        cmd,
                        env=env,
                        cwd=str(Path(self.config.session_dir).resolve()),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,  # Line buffered
                    )
                    
                    # Stream to both console and file
                    for line in process.stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        log_file.write(line)
                        log_file.flush()
                    
                    process.wait()
                    return_code = process.returncode
            else:
                # Interactive mode: pass through stdin/stdout/stderr for TUI
                # Note: stdout won't be captured to log file in interactive mode
                with open(stdout_log_path, 'w') as log_file:
                    log_file.write("# Interactive mode - stdout not captured\n")
                    log_file.write(f"# Command: {shlex.join(cmd)}\n")
                
                result = subprocess.run(
                    cmd,
                    env=env,
                    cwd=str(Path(self.config.session_dir).resolve()),
                    # Inherit stdin/stdout/stderr for interactive TUI
                )
                return_code = result.returncode
                
            return return_code
            
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")
            return 130
        except subprocess.SubprocessError as e:
            print(f"❌ Error running codex: {e}", file=sys.stderr)
            return 1
        finally:
            # Stop trace collector
            if collector:
                collector.stop()
            
            # Move history from CODEX_HOME to traces
            if codex_home:
                self._move_history_to_traces(codex_home)
            
            if self.config.verbose:
                print(f"📝 Stdout/stderr saved to: {stdout_log_path}")


def run(
    session_dir: str,
    read_only_dirs: list[str] | None = None,
    session_id: str = "1",
    model: str = "anthropic/claude-opus-4.5",
    model_provider: str = "openrouter",
    config_dir: str | None = None,
    prompt_file: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    **kwargs,
) -> int:
    """Convenience function to run Codex for a session.

    This provides a simpler programmatic interface.

    Args:
        session_dir: Path to the session directory (writable)
        read_only_dirs: List of read-only data directories
        session_id: Session identifier
        model: Model identifier
        model_provider: Model provider name
        config_dir: Optional path to config directory
        prompt_file: Optional path to custom prompt file
        dry_run: If True, print command without executing
        verbose: Enable verbose output
        **kwargs: Additional configuration options

    Returns:
        Exit code from codex execution
    """
    from argparse import Namespace

    # Build args namespace
    args = Namespace(
        session_dir=session_dir,
        read_only_dir=read_only_dirs or [],
        session_id=session_id,
        model=model,
        model_provider=model_provider,
        reasoning_effort=kwargs.get("reasoning_effort", "high"),
        config_dir=config_dir,
        prompt_file=prompt_file,
        policy_file=kwargs.get("policy_file"),
        profile=kwargs.get("profile", "sre_support_engineer"),
        full_auto=kwargs.get("full_auto", True),
        sandbox_mode=kwargs.get("sandbox_mode", "workspace-write"),
        network_access=kwargs.get("network_access", False),
        query=kwargs.get(
            "query",
            "analyze the incident snapshot in the read-only directories. Write the agent_output.json file at {output_path}",
        ),
        verbose=verbose,
        api_key_env=kwargs.get("api_key_env"),
        api_base_url=kwargs.get("api_base_url"),
        collect_traces=kwargs.get("collect_traces", False),
        otel_port=kwargs.get("otel_port", 4318),
    )

    config = ZeroConfig.from_args(args)
    runner = CodexRunner(config)
    return runner.run_session(dry_run=dry_run)
