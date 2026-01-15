"""
Configuration management for Zero.

Handles workspace setup, config file copying, and prompt rendering.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Path to the bundled config directory (zero-config/)
BUNDLED_CONFIG_DIR = Path(__file__).parent / "zero-config"

# Default prompt template within the bundled config
DEFAULT_PROMPT_TEMPLATE = BUNDLED_CONFIG_DIR / "prompts" / "react_shell_investigation.md"


@dataclass
class ZeroWorkspacePaths:
    """Paths within the Zero workspace."""

    workspace_dir: Path
    config_toml: Path  # workspace/config.toml
    prompts_dir: Path  # workspace/prompts/
    policy_dir: Path  # workspace/policy/
    traces_dir: Path  # workspace/traces/
    traces_jsonl: Path  # workspace/traces/traces.jsonl
    stdout_log: Path  # workspace/traces/stdout.log


def setup_workspace(
    *,
    workspace_dir: str,
    read_only_dirs: list[str],
    prompt_file_override: str | None = None,
    collect_traces: bool = False,
    otel_port: int = 4318,
    verbose: bool = False,
) -> ZeroWorkspacePaths:
    """Set up the workspace directory with config, prompts, and policies.

    This function:
    1. Creates the workspace directory structure
    2. Initializes a git repo if not present (Codex trusts git repos)
    3. Copies config.toml with modifications
    4. Copies prompts/ and policy/ directories
    5. Updates config with read-only dirs, OTEL settings, etc.

    Args:
        workspace_dir: Path to the workspace directory
        read_only_dirs: List of read-only data directories
        prompt_file_override: Optional custom prompt file path
        collect_traces: Whether to enable OTEL trace collection
        otel_port: Port for OTEL collector
        verbose: Enable verbose output

    Returns:
        ZeroWorkspacePaths with all relevant paths
    """
    ws = Path(workspace_dir).expanduser().resolve()

    # Create workspace structure
    ws.mkdir(parents=True, exist_ok=True)
    traces_dir = ws / "traces"
    traces_dir.mkdir(exist_ok=True)

    paths = ZeroWorkspacePaths(
        workspace_dir=ws,
        config_toml=ws / "config.toml",
        prompts_dir=ws / "prompts",
        policy_dir=ws / "policy",
        traces_dir=traces_dir,
        traces_jsonl=traces_dir / "traces.jsonl",
        stdout_log=traces_dir / "stdout.log",
    )

    # Initialize git repo if not present (Codex trusts git repos)
    _ensure_git_repo(ws, verbose=verbose)

    # Copy prompts directory
    _copy_directory(BUNDLED_CONFIG_DIR / "prompts", paths.prompts_dir, verbose=verbose)

    # Copy policy directory
    _copy_directory(BUNDLED_CONFIG_DIR / "policy", paths.policy_dir, verbose=verbose)

    # Generate config.toml with modifications
    _generate_config(
        paths=paths,
        read_only_dirs=read_only_dirs,
        prompt_file_override=prompt_file_override,
        collect_traces=collect_traces,
        otel_port=otel_port,
        verbose=verbose,
    )

    return paths


def _ensure_git_repo(workspace: Path, verbose: bool = False) -> None:
    """Initialize a git repo in the workspace if not present.

    Codex trusts directories that are git repositories, which allows
    custom instructions (experimental_instructions_file) to work.
    """
    git_dir = workspace / ".git"
    if git_dir.exists():
        if verbose:
            print(f"Git repo already exists: {workspace}")
        return

    try:
        result = subprocess.run(
            ["git", "init"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            if verbose:
                print(f"Initialized git repo: {workspace}")
        else:
            if verbose:
                print(f"Warning: git init failed: {result.stderr}", file=sys.stderr)
    except FileNotFoundError:
        if verbose:
            print("Warning: git not found, skipping repo initialization", file=sys.stderr)
    except Exception as e:
        if verbose:
            print(f"Warning: git init failed: {e}", file=sys.stderr)


def _copy_directory(src: Path, dst: Path, verbose: bool = False) -> None:
    """Copy a directory, overwriting if it exists."""
    if not src.exists():
        if verbose:
            print(f"Warning: source directory not found: {src}", file=sys.stderr)
        return

    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(src, dst)
    if verbose:
        print(f"Copied {src} → {dst}")


def _generate_config(
    *,
    paths: ZeroWorkspacePaths,
    read_only_dirs: list[str],
    prompt_file_override: str | None,
    collect_traces: bool,
    otel_port: int,
    verbose: bool,
) -> None:
    """Generate config.toml from bundled config with Zero-specific modifications.

    Modifications:
    - Update sandbox writable_roots to workspace
    - Configure OTEL if trace collection enabled
    - Add trust entry for workspace

    Note: experimental_instructions_file is NOT used because it's unreliable.
    Instead, prompts are passed directly to codex exec via runner.py.
    """
    src_config = BUNDLED_CONFIG_DIR / "config.toml"
    if not src_config.exists():
        raise FileNotFoundError(f"Bundled config.toml not found: {src_config}")

    content = src_config.read_text()

    # Copy custom prompt to workspace prompts dir (for interactive mode /prompts:name)
    if prompt_file_override:
        prompt_path = Path(prompt_file_override).expanduser().resolve()
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        dst_prompt = paths.prompts_dir / prompt_path.name
        shutil.copy2(prompt_path, dst_prompt)

    # Update writable_roots to workspace directory
    ws_str = str(paths.workspace_dir)
    content = _update_writable_roots(content, ws_str)

    # Update OTEL configuration if trace collection enabled
    if collect_traces:
        content = _add_otel_config(content, otel_port)

    # Add trust entry for workspace
    content = _add_trust_entry(content, ws_str)

    # Write the modified config
    paths.config_toml.write_text(content)
    if verbose:
        print(f"Generated config: {paths.config_toml}")


def _update_writable_roots(content: str, workspace_path: str) -> str:
    """Update writable_roots in the config to point to workspace."""
    import re

    # Match the writable_roots array and replace it
    pattern = r"(writable_roots\s*=\s*\[)[^\]]*(\])"
    replacement = rf'\g<1>\n    "{workspace_path}",\n\g<2>'

    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return new_content


def _add_otel_config(content: str, otel_port: int) -> str:
    """Add OTEL configuration section for trace collection."""
    otel_section = f"""
# Zero: OTEL tracing configuration (auto-generated for --collect-traces)
[otel]
log_user_prompt = true
exporter = {{ otlp-http = {{ endpoint = "http://localhost:{otel_port}/v1/logs", protocol = "binary" }} }}
"""
    # Add at the end of the file (before trust entry if present)
    return content.rstrip() + "\n" + otel_section


def _add_trust_entry(content: str, workspace_path: str) -> str:
    """Add a trust entry for the workspace directory.

    Adds:
        [projects."<workspace_path>"]
        trust_level = "trusted"
    """
    trust_section = f"""
# Zero: Mark workspace as trusted (auto-generated)
[projects."{workspace_path}"]
trust_level = "trusted"
"""

    # Add at the end of the file
    return content.rstrip() + "\n" + trust_section
