"""
Command-line interface for Agentz.

Handles argument parsing and orchestrates the Codex execution.
"""

import argparse
import os
import sys
from pathlib import Path

from .config import AgentZConfig
from .runner import CodexRunner


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="agentz",
        description="Run Codex agent against incident snapshots for SRE investigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with a scenario directory
  python -m agentz --scenario-dir /path/to/Scenario-1

  # With custom run ID and output directory
  python -m agentz --scenario-dir /path/to/Scenario-1 --run-id 42 --output-dir /tmp/reports

  # With custom model and API key
  python -m agentz --scenario-dir /path/to/Scenario-1 \\
    --model "anthropic/claude-opus-4.5" \\
    --model-provider openrouter \\
    --api-key-env OR_API_KEY

  # With custom config directory
  python -m agentz --scenario-dir /path/to/Scenario-1 --config-dir ./my-config

  # Custom prompt/instructions
  python -m agentz --scenario-dir /path/to/Scenario-1 --prompt-file ./custom_prompt.md

  # Run all scenarios in a directory
  python -m agentz --scenarios-base-dir /path/to/snapshots/sre/v0.1 --run-all

Environment Variables:
  OR_API_KEY          OpenRouter API key
  OPENAI_API_KEY      OpenAI API key
  ETE_API_KEY         ETE LiteLLM Proxy API key
  AZURE_OPENAI_KEY    Azure OpenAI API key
        """,
    )

    # Required arguments
    scenario_group = parser.add_mutually_exclusive_group(required=True)
    scenario_group.add_argument(
        "--scenario-dir",
        "-s",
        type=str,
        help="Path to the scenario directory containing snapshot data",
    )
    scenario_group.add_argument(
        "--scenarios-base-dir",
        type=str,
        help="Base directory containing multiple scenarios (use with --run-all or --scenario-name)",
    )

    # Scenario selection (when using --scenarios-base-dir)
    parser.add_argument(
        "--scenario-name",
        type=str,
        help="Name of specific scenario to run (e.g., 'Scenario-1') when using --scenarios-base-dir",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run all scenarios in --scenarios-base-dir",
    )

    # Output configuration
    parser.add_argument(
        "--run-id",
        "-r",
        type=str,
        default=os.environ.get("RUN_ID", "1"),
        help="Run identifier for output organization (default: $RUN_ID or '1')",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="/tmp/agentz-output/reports",
        help="Base output directory for agent_output.json files (default: /tmp/agentz-output/reports)",
    )

    # Model configuration
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="anthropic/claude-opus-4.5",
        help="Model identifier (default: anthropic/claude-opus-4.5)",
    )
    parser.add_argument(
        "--model-provider",
        type=str,
        default="openrouter",
        choices=["openrouter", "openai", "azure", "ete", "custom"],
        help="Model provider (default: openrouter)",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default="high",
        choices=["minimal", "low", "medium", "high"],
        help="Model reasoning effort level (default: high)",
    )

    # API configuration
    parser.add_argument(
        "--api-key-env",
        type=str,
        help="Environment variable name containing the API key (e.g., OR_API_KEY)",
    )
    parser.add_argument(
        "--api-base-url",
        type=str,
        help="Custom API base URL (overrides provider default)",
    )

    # Config directory
    parser.add_argument(
        "--config-dir",
        type=str,
        help="Path to agentz config directory (default: bundled config or auto-generated)",
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        help="Path to custom prompt/instructions file (overrides default SRE prompt)",
    )
    parser.add_argument(
        "--policy-file",
        type=str,
        help="Path to custom execution policy file",
    )

    # Profile configuration
    parser.add_argument(
        "--profile",
        type=str,
        default="sre_support_engineer",
        help="Codex profile to use (default: sre_support_engineer)",
    )

    # Execution options
    parser.add_argument(
        "--full-auto",
        action="store_true",
        default=True,
        help="Run in full-auto mode (default: True)",
    )
    parser.add_argument(
        "--no-full-auto",
        action="store_false",
        dest="full_auto",
        help="Disable full-auto mode",
    )
    parser.add_argument(
        "--sandbox-mode",
        type=str,
        default="workspace-write",
        choices=["workspace-write", "workspace-read", "off"],
        help="Sandbox mode for Codex (default: workspace-write)",
    )
    parser.add_argument(
        "--network-access",
        action="store_true",
        default=False,
        help="Allow network access in sandbox",
    )

    # Query/task configuration
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default="analyze the incident snapshot in this directory. Write the agent_output.json file at {output_path}",
        help="Task query to send to the agent (use {output_path} as placeholder)",
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would be executed without running it",
    )

    # Writable roots
    parser.add_argument(
        "--writable-root",
        action="append",
        default=[],
        help="Additional writable directory for sandbox (can be specified multiple times)",
    )

    # Tracing options
    parser.add_argument(
        "--collect-traces",
        action="store_true",
        default=False,
        help="Enable OpenTelemetry trace collection using otel-cli",
    )
    parser.add_argument(
        "--traces-output-dir",
        type=str,
        default=None,
        help="Directory for trace output files (default: {output_dir}/traces)",
    )
    parser.add_argument(
        "--otel-port",
        type=int,
        default=4318,
        help="Port for OTEL collector (default: 4318)",
    )

    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parsed_args = parse_args(args)

    try:
        # Build configuration from arguments
        config = AgentZConfig.from_args(parsed_args)

        if parsed_args.verbose:
            print(f"Configuration:")
            print(f"  Model: {config.model}")
            print(f"  Provider: {config.model_provider}")
            print(f"  Config dir: {config.config_dir}")
            print(f"  Prompt file: {config.prompt_file}")

        # Create runner
        runner = CodexRunner(config)

        # Handle different execution modes
        if parsed_args.scenarios_base_dir:
            if parsed_args.run_all:
                # Run all scenarios
                return runner.run_all_scenarios(
                    base_dir=parsed_args.scenarios_base_dir,
                    dry_run=parsed_args.dry_run,
                )
            elif parsed_args.scenario_name:
                # Run specific scenario
                scenario_dir = Path(parsed_args.scenarios_base_dir) / parsed_args.scenario_name
                return runner.run_scenario(
                    scenario_dir=str(scenario_dir),
                    dry_run=parsed_args.dry_run,
                )
            else:
                print("Error: --scenarios-base-dir requires either --run-all or --scenario-name", file=sys.stderr)
                return 1
        else:
            # Run single scenario
            return runner.run_scenario(
                scenario_dir=parsed_args.scenario_dir,
                dry_run=parsed_args.dry_run,
            )

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if parsed_args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

