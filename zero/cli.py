"""
Command-line interface for Zero.

Zero is a minimal Codex wrapper that sets up a workspace with proper config,
prompts, policies, and sandbox settings for reproducible agent runs.

Usage:
    zero [ZERO_ARGS...] -- [CODEX_ARGS...]

Zero-only flags:
    --workspace PATH       Writable workspace directory (becomes CODEX_HOME and cwd)
    --read-only-dir PATH   Read-only data directories (repeatable)
    --collect-traces       Enable OTEL trace collection
    --otel-port PORT       Port for OTEL collector (default: 4318)
    --prompt-file PATH     Prompt template file (exec mode: substituted and used as prompt)
    --variable KEY=VALUE   Variable substitution for prompt (repeatable, exec mode only)
    --output-file NAME     Expected output file (exec mode). Auto-retries if missing. (default: agent_output.json)
    --max-retries N        Max retries if output file not created (exec mode). (default: 5)

Everything after '--' is passed through to Codex unchanged (except validation).

In exec mode with --prompt-file:
    - Variables use $VARNAME format (uppercase, Codex-style)
    - Auto-provided: $WORKSPACE_DIR only
    - User must provide other variables via --variable "KEY=value"
    - LaTeX math ($L$, $v$, $P$) is NOT treated as variables (requires 2+ chars)
    - Validation fails if any $VARNAME remains unsubstituted
    - Any additional prompt after "exec" is appended to the substituted prompt
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import (
    BUNDLED_CONFIG_DIR,
    ZeroWorkspacePaths,
    setup_workspace,
)
from .runner import run_codex

# Codex flags that Zero reserves control over
FORBIDDEN_CODEX_FLAGS = {
    "-C": "Zero controls the working directory via --workspace",
    "--cd": "Zero controls the working directory via --workspace",
    "--json": "Zero always enables --json for exec mode; do not pass it explicitly",
}


def _validate_codex_args(codex_args: list[str]) -> None:
    """Validate that codex_args don't contain flags Zero reserves."""
    for i, arg in enumerate(codex_args):
        # Check exact matches
        if arg in FORBIDDEN_CODEX_FLAGS:
            raise ValueError(f"Cannot pass '{arg}' to Codex: {FORBIDDEN_CODEX_FLAGS[arg]}")
        # Check --flag=value form
        for flag in FORBIDDEN_CODEX_FLAGS:
            if arg.startswith(f"{flag}="):
                raise ValueError(f"Cannot pass '{flag}' to Codex: {FORBIDDEN_CODEX_FLAGS[flag]}")


def _split_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv into Zero args and Codex args at '--' boundary."""
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1 :]
    # If no '--', treat everything as Zero args (Codex args empty)
    return argv, []


def parse_zero_args(args: list[str]) -> argparse.Namespace:
    """Parse Zero-only arguments."""
    parser = argparse.ArgumentParser(
        prog="zero",
        description="Minimal Codex wrapper for reproducible agent runs against incident snapshots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Exec mode with prompt template (recommended)
  zero --workspace /tmp/work \\
       --read-only-dir ./Scenario-1 \\
       --prompt-file ./prompts/sre_react_shell_investigation.md \\
       -- exec -m "openai/o4-mini"

  # With additional instructions appended to prompt
  zero --workspace /tmp/work \\
       --read-only-dir ./Scenario-1 \\
       --prompt-file ./prompts/sre_react_shell_investigation.md \\
       -- exec -m "openai/o4-mini" "focus on the cart service"

  # With custom variables
  zero --workspace /tmp/work \\
       --read-only-dir ./Scenario-1 \\
       --prompt-file ./prompts/sre_react_shell_investigation.md \\
       --variable "custom_context=some value" \\
       -- exec -m "openai/o4-mini"

  # Interactive TUI mode (no prompt substitution)
  zero --workspace /tmp/work --read-only-dir ./Scenario-1 -- -m "openai/o4-mini"

  # With trace collection
  zero --workspace /tmp/work --read-only-dir ./Scenario-1 --collect-traces -- exec "investigate"

Notes:
  - Everything after '--' is passed to Codex unchanged.
  - Zero sets CODEX_HOME to the workspace directory.
  - Zero copies its bundled config (config.toml, prompts/, policy/) to workspace.
  - Zero always adds '--json' when 'exec' subcommand is used.
  - Do NOT pass -C/--cd or --json to Codex; Zero controls these.
  - In exec mode with --prompt-file, auto-variables are: {snapshot_dirs}, {output_path}, {workspace_dir}
""",
    )

    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        required=True,
        help="Workspace directory (writable). Becomes CODEX_HOME and cwd. Will be git-initialized if needed.",
    )

    parser.add_argument(
        "--read-only-dir",
        "-r",
        action="append",
        default=[],
        dest="read_only_dirs",
        help="Read-only data directory (can be specified multiple times)",
    )

    parser.add_argument(
        "--collect-traces",
        action="store_true",
        default=False,
        help="Enable OTEL trace collection to workspace/traces/traces.jsonl",
    )

    parser.add_argument(
        "--otel-port",
        type=int,
        default=4318,
        help="Port for OTEL collector (default: 4318)",
    )

    parser.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help="Prompt template file. In exec mode, variables are substituted and it becomes the prompt.",
    )

    parser.add_argument(
        "--variable",
        "-V",
        action="append",
        default=[],
        dest="variables",
        metavar="KEY=VALUE",
        help="Variable substitution for prompt template (repeatable). Keys are uppercased. E.g., --variable 'MY_VAR=value'",
    )

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

    parser.add_argument(
        "--output-file",
        type=str,
        default="agent_output.json",
        help="Expected output file name (exec mode only). If not created, Zero retries with 'resume --last'. Default: agent_output.json",
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Max retries if output file is not created (exec mode only). Default: 5",
    )

    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    if argv is None:
        argv = sys.argv[1:]

    # Split into Zero args and Codex args
    zero_argv, codex_args = _split_args(argv)

    # Parse Zero args
    try:
        args = parse_zero_args(zero_argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    # Validate Codex args don't contain reserved flags
    try:
        _validate_codex_args(codex_args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Setup workspace
    try:
        workspace_paths = setup_workspace(
            workspace_dir=args.workspace,
            read_only_dirs=args.read_only_dirs,
            prompt_file_override=args.prompt_file,
            collect_traces=args.collect_traces,
            otel_port=args.otel_port,
            verbose=args.verbose,
        )
    except Exception as e:
        print(f"Error setting up workspace: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Workspace: {workspace_paths.workspace_dir}")
        print(f"CODEX_HOME: {workspace_paths.workspace_dir}")
        print(f"Config: {workspace_paths.config_toml}")
        print(f"Prompts: {workspace_paths.prompts_dir}")
        print(f"Policy: {workspace_paths.policy_dir}")
        print(f"Read-only dirs: {args.read_only_dirs}")
        if args.collect_traces:
            print(f"Traces: {workspace_paths.traces_jsonl}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would run codex with args: {codex_args}")
        print(f"[DRY RUN] CODEX_HOME={workspace_paths.workspace_dir}")
        print(f"[DRY RUN] cwd={workspace_paths.workspace_dir}")
        return 0

    # Parse user variables
    user_variables = {}
    for var in args.variables:
        if "=" not in var:
            print(f"Error: Invalid variable format '{var}'. Expected KEY=VALUE", file=sys.stderr)
            return 1
        key, value = var.split("=", 1)
        user_variables[key] = value

    # Run Codex
    try:
        return run_codex(
            workspace_paths=workspace_paths,
            codex_args=codex_args,
            prompt_file=args.prompt_file,
            prompt_variables=user_variables,
            collect_traces=args.collect_traces,
            otel_port=args.otel_port,
            verbose=args.verbose,
            output_file=args.output_file,
            max_retries=args.max_retries,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error running Codex: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
