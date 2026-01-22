"""
Configuration management for Zero.

Handles workspace setup, config file copying, and prompt rendering.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

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


def _parse_yaml_frontmatter(prompt_content: str) -> dict | None:
    """Parse YAML frontmatter from prompt template.

    Returns dict with frontmatter data, or None if no frontmatter found.

    Example frontmatter:
    ---
    mcp_servers:
      - offline_incident_analysis
      - clickhouse
    ---
    """
    # Match YAML frontmatter: starts with ---, ends with ---
    pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(pattern, prompt_content, re.DOTALL)

    if not match:
        return None

    yaml_content = match.group(1)

    try:
        data = yaml.safe_load(yaml_content)
        # Return only if mcp_servers key exists and has values
        if data and "mcp_servers" in data and data["mcp_servers"]:
            return {"mcp_servers": data["mcp_servers"]}
    except yaml.YAMLError:
        # If YAML parsing fails, return None (backward compatibility)
        pass

    return None


def _filter_mcp_servers(content: str, required_servers: list[str]) -> str:
    """Filter MCP server configurations to only include required servers.

    Removes entire [mcp_servers.X] sections that are not in required_servers list.
    """
    if not required_servers:
        # If no servers specified, keep all (backward compatibility)
        return content

    # Use set for O(1) lookup
    required_set = set(required_servers)
    lines = content.split("\n")
    filtered_lines = []
    in_mcp_section = False
    current_server = None

    for line in lines:
        # Check if we're starting an MCP server section (main header only, not subsections)
        mcp_match = re.match(r"^\[mcp_servers\.([^\.\]]+)\]", line)

        if mcp_match:
            # Extract server name from section header
            current_server = mcp_match.group(1)
            in_mcp_section = True

            # Keep this server if it's in the required list
            if current_server in required_set:
                filtered_lines.append(line)
            else:
                # Comment out disabled server
                filtered_lines.append(f"# [mcp_servers.{current_server}] - disabled (not required by prompt template)")
            continue

        # Check if we're exiting MCP server sections
        if line.startswith("[") and not line.startswith("[mcp_servers."):
            in_mcp_section = False
            current_server = None

        # Handle line based on whether we're in a filtered section
        if in_mcp_section and current_server not in required_set:
            # Comment out lines in disabled sections
            filtered_lines.append(f"# {line}" if line.strip() and not line.strip().startswith("#") else line)
        else:
            # Keep lines in enabled sections or outside MCP sections
            filtered_lines.append(line)

    return "\n".join(filtered_lines)


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
    - Filter MCP servers based on prompt template frontmatter (if present)

    Note: experimental_instructions_file is NOT used because it's unreliable.
    Instead, prompts are passed directly to codex exec via runner.py.
    """
    src_config = BUNDLED_CONFIG_DIR / "config.toml"
    if not src_config.exists():
        raise FileNotFoundError(f"Bundled config.toml not found: {src_config}")

    content = src_config.read_text()

    # Parse prompt template for MCP server requirements
    required_mcp_servers = None
    if prompt_file_override:
        prompt_path = Path(prompt_file_override).expanduser().resolve()
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

        # Parse frontmatter to get required MCP servers
        prompt_content = prompt_path.read_text()
        frontmatter = _parse_yaml_frontmatter(prompt_content)
        if frontmatter and "mcp_servers" in frontmatter:
            required_mcp_servers = frontmatter["mcp_servers"]
            if verbose:
                print(f"Prompt requires MCP servers: {', '.join(required_mcp_servers)}")

        # Copy custom prompt to workspace prompts dir (for interactive mode /prompts:name)
        dst_prompt = paths.prompts_dir / prompt_path.name
        shutil.copy2(prompt_path, dst_prompt)

    # Filter MCP servers based on prompt requirements
    if required_mcp_servers is not None:
        content = _filter_mcp_servers(content, required_mcp_servers)

    # Update writable_roots to workspace directory
    ws_str = str(paths.workspace_dir)
    content = _update_writable_roots(content, ws_str)

    # Update OTEL configuration if trace collection enabled
    if collect_traces:
        content = _add_otel_config(content, otel_port)

    # Substitute environment variables in MCP server configs
    content = _substitute_env_vars(content)

    # Add trust entry for workspace
    content = _add_trust_entry(content, ws_str)

    # Write the modified config
    paths.config_toml.write_text(content)
    if verbose:
        print(f"Generated config: {paths.config_toml}")


def _update_writable_roots(content: str, workspace_path: str) -> str:
    """Update writable_roots in the config to point to workspace."""
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


def _substitute_env_vars(content: str) -> str:
    """Substitute environment variable placeholders in MCP server configs.

    Replaces ${VAR_NAME} style references with actual environment variable values.
    Provides sensible defaults for common variables.
    """
    # Default values for common environment variables
    defaults = {
        "CLICKHOUSE_HOST": "localhost",
        "CLICKHOUSE_PORT": "8123",
        "CLICKHOUSE_USER": "default",
        "CLICKHOUSE_PASSWORD": "",
        "CLICKHOUSE_PROXY_PATH": "",  # For reverse proxy paths (e.g., /clickhouse/clickhouse)
        "CLICKHOUSE_SECURE": "false",  # Use HTTP by default
        "CLICKHOUSE_VERIFY": "true",  # Verify SSL certificates
        "KUBECONFIG": "",  # Empty means MCP will use default ~/.kube/config
        "INSTANA_BASE_URL": "",  # Instana instance URL
        "INSTANA_API_TOKEN": "",  # Instana API token
    }

    def replace_env_var(match):
        var_name = match.group(1)
        return os.environ.get(var_name, defaults.get(var_name, ""))

    content = re.sub(r"\$\{([A-Z_]+)\}", replace_env_var, content)

    return content


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
