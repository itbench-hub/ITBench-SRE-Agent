"""
Codex CLI runner for Agentz.

Handles the execution of Codex CLI with proper environment and configuration.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Generator

from .config import AgentZConfig
from .tracing import OtelTraceCollector


class CodexRunner:
    """Runs Codex CLI with the given configuration."""

    def __init__(self, config: AgentZConfig):
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

        # Set RUN_ID for query interpolation
        env["RUN_ID"] = self.config.run_id

        # Ensure API key environment variable is available
        if self.config.api_key_env:
            # Check if already set
            if self.config.api_key_env not in env:
                print(
                    f"Warning: API key environment variable {self.config.api_key_env} is not set",
                    file=sys.stderr,
                )

        return env

    def _build_command(self, scenario_dir: str, query: str) -> list[str]:
        """Build the codex CLI command."""
        cmd = ["codex", "exec"]

        # Add full-auto flag if enabled
        if self.config.full_auto:
            cmd.append("--full-auto")

        # Explicitly set writable roots via CLI config to ensure they are applied
        # format: --config sandbox_workspace_write.writable_roots='["/path/1", "/path/2"]'
        # We use root-level config as this has proven to work reliably in testing
        roots = self.config.get_all_writable_roots()
        roots_toml = str(list(roots)).replace("'", '"')  # Python list repr uses single quotes, TOML needs double
        cmd.extend(["--config", f"sandbox_workspace_write.writable_roots={roots_toml}"])

        # Add working directory
        cmd.extend(["-C", scenario_dir])

        # Add the query
        cmd.append(query)

        return cmd

    def run_scenario(
        self,
        scenario_dir: str,
        dry_run: bool = False,
    ) -> int:
        """Run Codex against a single scenario directory.

        Args:
            scenario_dir: Path to the scenario directory
            dry_run: If True, print command without executing

        Returns:
            Exit code from codex execution (0 = success)
        """
        scenario_path = Path(scenario_dir)
        if not scenario_path.exists():
            raise FileNotFoundError(f"Scenario directory not found: {scenario_dir}")

        scenario_name = scenario_path.name
        query = self.config.get_query()
        output_path = self.config.get_output_path()

        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # Setup tracing if enabled
        traces_output_path = None
        collector = None
        if self.config.collect_traces:
            traces_output_path = self.config.get_traces_output_path()
            # Ensure traces directory exists
            Path(traces_output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build command and environment
        cmd = self._build_command(str(scenario_path.resolve()), query)
        env = self._get_environment()

        if self.config.verbose or dry_run:
            print(f"\n{'='*60}")
            print(f"Scenario: {scenario_name}")
            print(f"Directory: {scenario_dir}")
            print(f"Output: {output_path}")
            if traces_output_path:
                print(f"Traces: {traces_output_path}")
            print(f"{'='*60}")
            print(f"\nEnvironment:")
            print(f"  CODEX_HOME={env.get('CODEX_HOME', 'not set')}")
            print(f"  RUN_ID={env.get('RUN_ID', 'not set')}")
            if self.config.api_key_env:
                key_set = self.config.api_key_env in env
                print(f"  {self.config.api_key_env}={'[set]' if key_set else '[not set]'}")
            print(f"\nCommand:")
            print(f"  {' '.join(cmd)}")
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
        print(f"🚀 Running Codex on {scenario_name}...")
        
        # Setup stdout/stderr capture alongside traces
        stdout_log_path = None
        if traces_output_path:
            stdout_log_path = traces_output_path.replace('.jsonl', '_stdout.log')
        
        try:
            if stdout_log_path:
                # Capture stdout/stderr to file while also showing on console
                with open(stdout_log_path, 'w') as log_file:
                    process = subprocess.Popen(
                        cmd,
                        env=env,
                        cwd=str(scenario_path.resolve()),
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
                    return process.returncode
            else:
                # No logging, just stream to console
                result = subprocess.run(
                    cmd,
                    env=env,
                    cwd=str(scenario_path.resolve()),
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
                return result.returncode
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
            if stdout_log_path and self.config.verbose:
                print(f"📝 Stdout/stderr saved to: {stdout_log_path}")

    def find_scenarios(self, base_dir: str) -> Generator[Path, None, None]:
        """Find all scenario directories in the base directory.

        Looks for directories matching 'Scenario-*' pattern.
        """
        base_path = Path(base_dir)
        if not base_path.exists():
            raise FileNotFoundError(f"Base directory not found: {base_dir}")

        # Look for Scenario-* directories
        for item in sorted(base_path.iterdir()):
            if item.is_dir() and item.name.startswith("Scenario-"):
                yield item

    def run_all_scenarios(
        self,
        base_dir: str,
        dry_run: bool = False,
    ) -> int:
        """Run Codex against all scenarios in a base directory.

        Args:
            base_dir: Path to directory containing Scenario-* subdirectories
            dry_run: If True, print commands without executing

        Returns:
            Exit code (0 if all succeeded, 1 if any failed)
        """
        scenarios = list(self.find_scenarios(base_dir))

        if not scenarios:
            print(f"No scenarios found in {base_dir}", file=sys.stderr)
            return 1

        print(f"Found {len(scenarios)} scenarios")

        results: dict[str, int] = {}
        failed = 0

        for i, scenario_path in enumerate(scenarios, 1):
            print(f"\n{'='*60}")
            print(f"[{i}/{len(scenarios)}] {scenario_path.name}")
            print(f"{'='*60}")

            exit_code = self.run_scenario(str(scenario_path), dry_run=dry_run)
            results[scenario_path.name] = exit_code

            if exit_code != 0:
                failed += 1
                print(f"❌ {scenario_path.name} failed with exit code {exit_code}")
            else:
                print(f"✅ {scenario_path.name} completed successfully")

        # Print summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Total: {len(scenarios)}")
        print(f"Passed: {len(scenarios) - failed}")
        print(f"Failed: {failed}")

        if failed > 0:
            print("\nFailed scenarios:")
            for name, code in results.items():
                if code != 0:
                    print(f"  - {name} (exit code: {code})")

        return 1 if failed > 0 else 0


def run(
    scenario_dir: str,
    run_id: str = "1",
    model: str = "anthropic/claude-opus-4.5",
    model_provider: str = "openrouter",
    output_dir: str = "/tmp/agentz-output/reports",
    config_dir: str | None = None,
    prompt_file: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    **kwargs,
) -> int:
    """Convenience function to run Codex against a scenario.

    This provides a simpler programmatic interface.

    Args:
        scenario_dir: Path to the scenario directory
        run_id: Run identifier
        model: Model identifier
        model_provider: Model provider name
        output_dir: Output directory for results
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
        scenario_dir=scenario_dir,
        scenarios_base_dir=None,
        run_id=run_id,
        model=model,
        model_provider=model_provider,
        reasoning_effort=kwargs.get("reasoning_effort", "high"),
        output_dir=output_dir,
        config_dir=config_dir,
        prompt_file=prompt_file,
        policy_file=kwargs.get("policy_file"),
        profile=kwargs.get("profile", "sre_support_engineer"),
        full_auto=kwargs.get("full_auto", True),
        sandbox_mode=kwargs.get("sandbox_mode", "workspace-write"),
        network_access=kwargs.get("network_access", False),
        writable_root=kwargs.get("writable_roots", []),
        query=kwargs.get(
            "query",
            "analyze the incident snapshot in this directory. Write the agent_output.json file at {output_path}",
        ),
        verbose=verbose,
        api_key_env=kwargs.get("api_key_env"),
        api_base_url=kwargs.get("api_base_url"),
    )

    config = AgentZConfig.from_args(args)
    runner = CodexRunner(config)
    return runner.run_scenario(scenario_dir, dry_run=dry_run)

