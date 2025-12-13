"""
Codex CLI runner for Zero.

Handles the execution of Codex CLI with proper environment and configuration.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ZeroWorkspacePaths
from .tracing import OtelTraceCollector


def run_codex(
    *,
    workspace_paths: ZeroWorkspacePaths,
    codex_args: list[str],
    prompt_file: str | None = None,
    prompt_variables: dict[str, str] | None = None,
    collect_traces: bool = False,
    otel_port: int = 4318,
    verbose: bool = False,
    output_file: str = "agent_output.json",
    max_retries: int = 5,
) -> int:
    """Run Codex with the workspace configuration.

    Args:
        workspace_paths: Paths within the workspace
        codex_args: Arguments to pass through to Codex (after validation)
        prompt_file: Optional prompt template file (for exec mode)
        prompt_variables: User-provided variables for prompt substitution
        collect_traces: Whether to collect OTEL traces
        otel_port: Port for OTEL collector
        verbose: Enable verbose output
        output_file: Expected output file name (exec mode only)
        max_retries: Max retries if output file not created (exec mode only)

    Returns:
        Exit code from Codex
    """
    # Validate codex is available
    if not shutil.which("codex"):
        print(
            "Error: codex CLI not found in PATH. Install it:\n"
            "  npm install -g @openai/codex\n"
            "or\n"
            "  brew install codex",
            file=sys.stderr,
        )
        return 1

    # Check if this is exec mode
    is_exec_mode = "exec" in codex_args or (codex_args and codex_args[0] == "e")

    # Handle prompt substitution (for both exec and interactive mode when --prompt-file is provided)
    # Writes substituted prompt to AGENTS.md (Codex reads this automatically)
    # User query (if any) is passed directly to Codex CLI
    if prompt_file:
        try:
            codex_args = _process_prompt_to_agents_md(
                prompt_file=prompt_file,
                codex_args=codex_args,
                workspace_paths=workspace_paths,
                prompt_variables=prompt_variables or {},
                is_exec_mode=is_exec_mode,
                verbose=verbose,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Build environment
    env = _build_environment(workspace_paths)

    # Working directory is the workspace
    cwd = str(workspace_paths.workspace_dir)

    # Output file path for retry checking (exec mode only)
    output_file_path = workspace_paths.workspace_dir / output_file

    # Start trace collector if enabled
    collector = None
    if collect_traces:
        collector = OtelTraceCollector(
            output_file=workspace_paths.traces_jsonl,
            port=otel_port,
            verbose=verbose,
        )
        try:
            collector.start()
        except Exception as e:
            print(f"Warning: Failed to start trace collector: {e}", file=sys.stderr)
            collector = None

    # Run Codex (with retry logic for exec mode)
    try:
        return _run_with_retry(
            codex_args=codex_args,
            env=env,
            cwd=cwd,
            stdout_log=workspace_paths.stdout_log,
            is_exec_mode=is_exec_mode,
            verbose=verbose,
            output_file_path=output_file_path,
            max_retries=max_retries,
        )
    finally:
        if collector:
            collector.stop()


def _process_prompt_to_agents_md(
    *,
    prompt_file: str,
    codex_args: list[str],
    workspace_paths: ZeroWorkspacePaths,
    prompt_variables: dict[str, str],
    is_exec_mode: bool,
    verbose: bool,
) -> list[str]:
    """Process prompt template: substitute variables and write to AGENTS.md.

    Variables use $VARNAME format (Codex-style, uppercase, 2+ chars).
    This avoids confusion with LaTeX math like $L$, $v$, $P$.

    Auto-provided: $WORKSPACE_DIR only.
    User must provide other variables via --variable.

    The substituted prompt is written to AGENTS.md in the workspace.
    Codex automatically reads AGENTS.md for project instructions.
    User query (if any) is left in codex_args to be passed directly to Codex.

    Args:
        prompt_file: Path to the prompt template
        codex_args: Original codex arguments (user query stays intact)
        workspace_paths: Workspace paths for auto-variables
        prompt_variables: User-provided variables (keys should be UPPERCASE)
        is_exec_mode: Whether this is exec mode (not used but kept for consistency)
        verbose: Enable verbose output

    Returns:
        codex_args (unchanged - user query stays in args)

    Raises:
        ValueError: If prompt file not found or unsubstituted placeholders remain
    """
    # Read prompt template
    prompt_path = Path(prompt_file).expanduser().resolve()
    if not prompt_path.exists():
        raise ValueError(f"Prompt file not found: {prompt_path}")

    content = prompt_path.read_text()

    # Build auto-variables (only WORKSPACE_DIR is auto-provided)
    # User must provide other variables like $SNAPSHOT_DIRS, $OUTPUT_PATH via --variable
    auto_vars = {
        "WORKSPACE_DIR": str(workspace_paths.workspace_dir),
    }

    # Normalize user-vars to uppercase and merge (user-vars take precedence)
    normalized_user_vars = {k.upper(): v for k, v in prompt_variables.items()}
    all_vars = {**auto_vars, **normalized_user_vars}

    # Substitute variables using $VARNAME pattern
    # Pattern: $ followed by 2+ uppercase letters/digits/underscores
    # This avoids matching LaTeX math like $L$, $v$, $P$ (single char)
    for key, value in all_vars.items():
        content = content.replace(f"${key}", value)

    # Validate no unsubstituted $VARNAME placeholders remain
    # Match: $ + uppercase letter + one or more uppercase letters/digits/underscores
    # This requires at least 2 chars total, avoiding LaTeX $L$, $P$, $v$
    remaining = re.findall(r"\$([A-Z][A-Z0-9_]+)", content)
    if remaining:
        unique_remaining = sorted(set(remaining))
        raise ValueError(
            f"Unsubstituted variables in prompt: ${', $'.join(unique_remaining)}. "
            f"Provide them via --variable KEY=VALUE"
        )

    # Write substituted prompt to AGENTS.md
    # Codex automatically reads this file for project instructions
    agents_md_path = workspace_paths.workspace_dir / "AGENTS.md"
    agents_md_path.write_text(content)

    if verbose:
        print(f"Prompt template: {prompt_path}")
        print(f"Variables substituted: {list(all_vars.keys())}")
        print(f"Substituted prompt written to: {agents_md_path} ({len(content)} chars)")

    # Return codex_args unchanged - user query (if any) stays in args
    return codex_args




def _run_with_retry(
    *,
    codex_args: list[str],
    env: dict[str, str],
    cwd: str,
    stdout_log: Path,
    is_exec_mode: bool,
    verbose: bool,
    output_file_path: Path,
    max_retries: int,
) -> int:
    """Run Codex with auto-retry logic for exec mode.

    If exec mode and output file is not created after Codex exits,
    automatically retry using 'resume --last' up to max_retries times.

    Args:
        codex_args: Original Codex arguments
        env: Environment variables
        cwd: Working directory
        stdout_log: Path for stdout logging
        is_exec_mode: Whether this is exec mode
        verbose: Enable verbose output
        output_file_path: Expected output file to check for
        max_retries: Max retry attempts

    Returns:
        Exit code from final Codex run
    """
    current_args = codex_args
    attempt = 0

    while True:
        attempt += 1
        cmd = _build_command(current_args)

        if verbose:
            print(f"\n{'=' * 60}")
            print(f"Attempt: {attempt}/{max_retries + 1}")
            print(f"CODEX_HOME: {env['CODEX_HOME']}")
            print(f"Working directory: {cwd}")
            # Show command with truncated prompt
            cmd_display = []
            for arg in cmd:
                if len(arg) > 200:
                    cmd_display.append(f"<prompt: {len(arg)} chars>")
                else:
                    cmd_display.append(arg)
            print(f"Command: {cmd_display}")
            print(f"{'=' * 60}\n")

        # Run Codex
        exit_code = _execute_codex(
            cmd=cmd,
            env=env,
            cwd=cwd,
            stdout_log=stdout_log,
            is_exec_mode=is_exec_mode,
            verbose=verbose,
        )

        # If not exec mode or output file exists, we're done
        if not is_exec_mode:
            return exit_code

        if output_file_path.exists():
            if verbose:
                print(f"\n✓ Output file created: {output_file_path}")
            return exit_code

        # Output file not created - check if we should retry
        retries_remaining = max_retries - attempt + 1
        if retries_remaining <= 0:
            print(
                f"\n⚠ Output file not found after {attempt} attempts: {output_file_path.name}",
                file=sys.stderr,
            )
            return exit_code

        # Build resume command
        print(
            f"\n⚠ Output file not found: {output_file_path.name}. "
            f"Retrying with 'resume --last' ({retries_remaining} retries left)...",
            file=sys.stderr,
        )

        resume_message = (
            f"I don't see {output_file_path.name} file. "
            f"Please resume the investigation and make sure to create the {output_file_path.name} file as instructed earlier."
        )

        # Build new args: original args + resume --last "message"
        # Need to insert resume --last before any trailing query
        current_args = _build_resume_args(codex_args, resume_message)


def _build_resume_args(codex_args: list[str], resume_message: str) -> list[str]:
    """Build args for resume command.

    Takes original codex args and appends: resume --last "message"
    """
    # Simply append resume --last to the original args
    return codex_args + ["resume", "--last", resume_message]


def _build_command(codex_args: list[str]) -> list[str]:
    """Build the codex command with required flags.

    Always adds --json when 'exec' subcommand is detected.
    """
    cmd = ["codex"]

    # Check if this is exec mode
    is_exec_mode = "exec" in codex_args or (codex_args and codex_args[0] == "e")

    # Add codex args
    cmd.extend(codex_args)

    # Always add --json for exec mode (after args so it doesn't interfere with subcommand)
    if is_exec_mode and "--json" not in codex_args:
        # Insert --json after 'exec' or 'e'
        try:
            exec_idx = codex_args.index("exec")
        except ValueError:
            try:
                exec_idx = codex_args.index("e")
            except ValueError:
                exec_idx = -1

        if exec_idx >= 0:
            # Rebuild command with --json after exec
            cmd = ["codex"] + codex_args[: exec_idx + 1] + ["--json"] + codex_args[exec_idx + 1 :]

    return cmd


def _build_environment(workspace_paths: ZeroWorkspacePaths) -> dict[str, str]:
    """Build environment variables for Codex execution."""
    env = os.environ.copy()

    # Set CODEX_HOME to workspace directory
    # This is the key setting - Codex reads config.toml from here
    env["CODEX_HOME"] = str(workspace_paths.workspace_dir)

    return env


def _execute_codex(
    *,
    cmd: list[str],
    env: dict[str, str],
    cwd: str,
    stdout_log: Path,
    is_exec_mode: bool,
    verbose: bool,
) -> int:
    """Execute the Codex command.

    For exec mode: captures stdout to log file while streaming to console.
    For interactive mode: passes through stdin/stdout/stderr.
    """
    stdout_log.parent.mkdir(parents=True, exist_ok=True)

    if is_exec_mode:
        # Exec mode: capture output to log while streaming
        with open(stdout_log, "w") as log_file:
            process = subprocess.Popen(
                cmd,
                env=env,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Stream to both console and log file
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log_file.write(line)
                log_file.flush()

            process.wait()
            return process.returncode
    else:
        # Interactive mode: pass through for TUI
        with open(stdout_log, "w") as log_file:
            log_file.write(f"# Interactive mode - command: {shlex.join(cmd)}\n")

        result = subprocess.run(cmd, env=env, cwd=cwd)
        return result.returncode
