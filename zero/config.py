"""
Configuration management for Zero.

Handles dynamic configuration generation with proper path resolution.
"""

import os
import tempfile
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    # Fallback for older Python versions if needed, though 3.11+ required
    import tomli as tomllib


# Path to bundled prompt file
BUNDLED_PROMPT_PATH = Path(__file__).parent / "zero-config" / "prompts" / "sre_support_engineer.md"

# Default path to tools manifest (relative to workspace root)
DEFAULT_TOOLS_MANIFEST = Path(__file__).parent.parent / "sre_tools" / "manifest.toml"


def load_tools_manifest(manifest_path: Path | str | None = None) -> dict[str, Any]:
    """Load the MCP tools manifest from a TOML file.
    
    Args:
        manifest_path: Path to manifest.toml. If None, uses the default bundled manifest.
        
    Returns:
        Dictionary containing the manifest data with 'tools' key.
        
    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest file is invalid.
    """
    path = Path(manifest_path) if manifest_path else DEFAULT_TOOLS_MANIFEST
    
    if not path.exists():
        # Return empty manifest if not found (tools are optional)
        return {"tools": {}}
    
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        print(f"Warning: Failed to parse tools manifest {path}: {e}", file=sys.stderr)
        return {"tools": {}}
    
    # Ensure 'tools' key exists
    if "tools" not in data:
        data["tools"] = {}
    
    return data

# Default execution policy
DEFAULT_POLICY = """# SRE Support Engineer Execution Policy
# Auto-allows kubectl commands for Kubernetes incident investigation

# Auto-allow all kubectl read operations
prefix_rule(
    pattern = ["kubectl", ["get", "describe", "logs", "top", "explain", "config", "api-resources", "api-versions"]],
    decision = "allow",
)

# Auto-allow kubectl with specific flags commonly used in investigation
prefix_rule(
    pattern = ["kubectl", "get"],
    decision = "allow",
)

prefix_rule(
    pattern = ["kubectl", "describe"],
    decision = "allow",
)

prefix_rule(
    pattern = ["kubectl", "logs"],
    decision = "allow",
)

prefix_rule(
    pattern = ["kubectl", "events"],
    decision = "allow",
)

prefix_rule(
    pattern = ["kubectl", "top"],
    decision = "allow",
)

# Auto-allow cat/head/tail for reading snapshot files
prefix_rule(
    pattern = ["cat"],
    decision = "allow",
)

prefix_rule(
    pattern = ["head"],
    decision = "allow",
)

prefix_rule(
    pattern = ["tail"],
    decision = "allow",
)

prefix_rule(
    pattern = ["ls"],
    decision = "allow",
)

prefix_rule(
    pattern = ["find"],
    decision = "allow",
)

prefix_rule(
    pattern = ["grep"],
    decision = "allow",
)

# Forbid destructive kubectl operations
prefix_rule(
    pattern = ["kubectl", ["delete", "apply", "create", "patch", "edit", "replace", "scale"]],
    decision = "forbidden",
)

# Forbid any code modification commands
prefix_rule(
    pattern = ["rm"],
    decision = "forbidden",
)

prefix_rule(
    pattern = ["mv"],
    decision = "forbidden",
)
"""


# Provider configurations
PROVIDER_CONFIGS = {
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OR_API_KEY",
        "wire_api": "chat",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "wire_api": "responses",
    },
    "ete": {
        "name": "ETE LITELLM PROXY",
        "base_url": "https://ete-litellm.ai-models.vpc-int.res.ibm.com",
        "env_key": "ETE_API_KEY",
        "wire_api": "chat",
    },
    "azure": {
        "name": "Azure OpenAI",
        "base_url": "",  # Must be provided
        "env_key": "AZURE_OPENAI_API_KEY",
        "wire_api": "responses",
    },
}


@dataclass
class ZeroConfig:
    """Configuration for Zero execution."""

    # Model configuration
    model: str = "anthropic/claude-opus-4.5"
    model_provider: str = "openrouter"
    reasoning_effort: str = "high"
    reasoning_summary: str = "detailed"

    # API configuration
    api_key_env: str | None = None
    api_base_url: str | None = None

    # Session and data directories
    session_dir: str = "/tmp/zero-session"  # Writable session directory
    read_only_dirs: list[str] = field(default_factory=list)  # Read-only data directories

    # Config paths
    config_dir: str | None = None
    prompt_file: str | None = None
    policy_file: str | None = None

    # Session configuration
    session_id: str = "1"

    # Execution options
    profile: str = "sre_support_engineer"
    full_auto: bool = True
    sandbox_mode: str = "workspace-write"
    network_access: bool = False

    # Query template (supports {output_path} and {snapshot_dirs} placeholders)
    query_template: str = "Analyze the incident snapshot in these directories: {snapshot_dirs}. Write the diagnosis to {output_path}"

    # Verbose mode
    verbose: bool = False
    
    # Clean session before running
    clean: bool = False

    # Tracing configuration
    collect_traces: bool = False
    otel_port: int = 4318
    
    # Dynamic providers loaded from agent.toml
    model_providers: dict = field(default_factory=lambda: PROVIDER_CONFIGS.copy())
    
    # MCP Tools configuration
    enabled_tools: list[str] = field(default_factory=list)  # List of tool names to enable
    tools_manifest_path: str | None = None  # Path to custom manifest.toml
    _tools_manifest: dict = field(default_factory=dict, repr=False)  # Cached manifest data

    # Internal state
    _temp_config_dir: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

    @classmethod
    def from_args(cls, args: Any) -> "ZeroConfig":
        """Create configuration from parsed command-line arguments."""
        # Load agent.toml
        agent_toml_path = Path(__file__).parent / "zero-config" / "agent.toml"
        toml_data = {}
        if agent_toml_path.exists():
            try:
                with open(agent_toml_path, "rb") as f:
                    toml_data = tomllib.load(f)
            except Exception as e:
                print(f"Warning: Failed to load agent.toml: {e}", file=sys.stderr)
        
        # Merge providers
        toml_providers = toml_data.get("model_providers", {})
        all_providers = PROVIDER_CONFIGS.copy()
        all_providers.update(toml_providers)

        # Determine profile
        cli_profile = getattr(args, "profile", None)
        profile = cli_profile or toml_data.get("profile", "sre_support_engineer")
        profile_data = toml_data.get("profiles", {}).get(profile, {})

        # Determine Model & Provider (CLI > Profile > Default)
        cli_model = getattr(args, "model", None)
        model = cli_model or profile_data.get("model", "anthropic/claude-opus-4.5")
        
        cli_provider = getattr(args, "model_provider", None)
        model_provider = cli_provider or profile_data.get("model_provider", "openrouter")

        # Determine API key environment variable
        api_key_env = getattr(args, "api_key_env", None)
        if not api_key_env:
            provider_config = all_providers.get(model_provider, {})
            api_key_env = provider_config.get("env_key")

        # Session directory
        session_dir = getattr(args, "session_dir", "/tmp/zero-session")
        
        # Read-only directories
        read_only_dirs = list(getattr(args, "read_only_dir", []))
        
        # MCP Tools configuration
        enabled_tools = list(getattr(args, "tools", []))
        tools_manifest_path = getattr(args, "tools_manifest", None)
        
        # Load tools manifest
        tools_manifest = load_tools_manifest(tools_manifest_path)

        return cls(
            model=model,
            model_provider=model_provider,
            reasoning_effort=getattr(args, "reasoning_effort", "high"),
            api_key_env=api_key_env,
            api_base_url=getattr(args, "api_base_url", None),
            session_dir=session_dir,
            read_only_dirs=read_only_dirs,
            config_dir=getattr(args, "config_dir", None),
            prompt_file=getattr(args, "prompt_file", None),
            policy_file=getattr(args, "policy_file", None),
            session_id=getattr(args, "session_id", "1"),
            profile=profile,
            full_auto=getattr(args, "full_auto", True),
            sandbox_mode=getattr(args, "sandbox_mode", "workspace-write"),
            network_access=getattr(args, "network_access", False),
            query_template=getattr(args, "query", "Analyze the incident snapshot in these directories: {snapshot_dirs}. Write the diagnosis to {output_path}"),
            verbose=getattr(args, "verbose", False),
            clean=getattr(args, "clean", False),
            collect_traces=getattr(args, "collect_traces", False),
            otel_port=getattr(args, "otel_port", 4318),
            model_providers=all_providers,
            enabled_tools=enabled_tools,
            tools_manifest_path=tools_manifest_path,
            _tools_manifest=tools_manifest,
        )

    def clean_session_dir(self) -> None:
        """Remove all contents from session directory and reinitialize.
        
        This completely resets the session directory, removing:
        - All files and subdirectories
        - The .git repository
        
        Then reinitializes the directory structure with a fresh git repo.
        """
        import shutil
        
        session_path = Path(self.session_dir)
        
        if session_path.exists():
            # Remove all contents
            for item in session_path.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            
            if self.verbose:
                print(f"Cleaned session directory: {session_path}")

    def setup_session_dir(self, clean: bool = False) -> None:
        """Create session directory structure as a git repository.
        
        Args:
            clean: If True, remove all existing contents before setup.
        
        Structure:
            session_dir/
            ├── .git/       # Git repository (for Codex trust + user versioning)
            ├── code/       # Agent-written code
            ├── plans/      # Final action plans
            ├── traces/     # OTEL traces, stdout logs, persistence
            └── output.json # Final output file
        
        The git repo ensures Codex treats this as a trusted workspace.
        If user already has a git repo here, we leave it untouched (unless clean=True).
        """
        import subprocess
        
        session_path = Path(self.session_dir)
        
        # Clean if requested
        if clean:
            self.clean_session_dir()
        
        # Create subdirectories
        (session_path / "code").mkdir(parents=True, exist_ok=True)
        (session_path / "plans").mkdir(parents=True, exist_ok=True)
        (session_path / "traces").mkdir(parents=True, exist_ok=True)
        
        # Initialize git repo if not already a git directory
        # This makes Codex trust this directory as a workspace
        git_dir = session_path / ".git"
        if not git_dir.exists():
            result = subprocess.run(
                ["git", "init"],
                cwd=session_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                # Log warning but don't fail - git init is optional
                import sys
                print(f"Warning: Failed to initialize git repo: {result.stderr}", file=sys.stderr)
            elif self.verbose:
                print(f"Initialized git repository in: {session_path}")

    def get_session_subdirs(self) -> dict[str, Path]:
        """Get paths to session subdirectories."""
        session_path = Path(self.session_dir)
        return {
            "code": session_path / "code",
            "plans": session_path / "plans",
            "traces": session_path / "traces",
            "output": session_path / "output.json",
        }

    def get_effective_config_dir(self) -> str:
        """Get the effective configuration directory, creating a temp one if needed.
        
        Always generates a temp config to ensure proper settings for session-based operation.
        """
        return self._create_temp_config_dir()

    def _create_temp_config_dir(self) -> str:
        """Create a temporary configuration directory with generated config files."""
        self._temp_config_dir = tempfile.TemporaryDirectory(prefix="zero-config-")
        temp_path = Path(self._temp_config_dir.name)

        # Create subdirectories
        (temp_path / "prompts").mkdir()
        (temp_path / "policy").mkdir()

        # Generate prompt file
        prompt_content = self._get_prompt_content()
        prompt_file = temp_path / "prompts" / f"{self.profile}.md"
        prompt_file.write_text(prompt_content)

        # Generate policy file
        policy_content = self._get_policy_content()
        policy_file = temp_path / "policy" / f"{self.profile}.codexpolicy"
        policy_file.write_text(policy_content)

        # Generate config.toml
        config_content = self._generate_config_toml(
            prompt_path=str(prompt_file),
        )
        config_file = temp_path / "config.toml"
        config_file.write_text(config_content)

        if self.verbose:
            print(f"\n[DEBUG] Generated config at: {config_file}")
            print(f"[DEBUG] Config contents:\n{config_content}")

        return str(temp_path)

    def _get_prompt_content(self) -> str:
        """Get prompt content from file.
        
        Uses bundled prompt file, or custom file if --prompt-file specified.
        Supports variable substitution for:
          - {output_path} - where to write the final output
          - {snapshot_dirs} - read-only directories with incident data
          - {session_dir} - writable session directory
        """
        # Use custom prompt file if specified, otherwise bundled
        prompt_path = Path(self.prompt_file) if self.prompt_file else BUNDLED_PROMPT_PATH
        
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        
        content = prompt_path.read_text()
        
        # Template substitution
        output_path = self.get_output_path()
        session_path = str(Path(self.session_dir).resolve())
        
        content = content.replace("{output_path}", output_path)
        content = content.replace("{session_dir}", session_path)
        
        # Format read-only directories as a bulleted list with absolute paths
        if self.read_only_dirs:
            dirs_list = "\n".join([f"- {str(Path(d).resolve())}" for d in self.read_only_dirs])
        else:
            dirs_list = "- (No read-only directories provided)"
        
        content = content.replace("{snapshot_dirs}", dirs_list)
            
        return content

    def _get_policy_content(self) -> str:
        """Get policy content from file or return default."""
        if self.policy_file:
            policy_path = Path(self.policy_file)
            if policy_path.exists():
                return policy_path.read_text()
            raise FileNotFoundError(f"Policy file not found: {self.policy_file}")
        return DEFAULT_POLICY

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Get list of available tools from the manifest.
        
        Returns:
            List of tool info dictionaries with 'name', 'description', 'type' keys.
        """
        tools = []
        for name, config in self._tools_manifest.get("tools", {}).items():
            tools.append({
                "name": name,
                "description": config.get("description", "No description"),
                "type": config.get("type", "unknown"),
            })
        return tools

    def _generate_mcp_servers_section(self) -> str:
        """Generate the [mcp_servers.*] sections for enabled tools.
        
        Supports placeholders:
        - {python} - Replaced with sys.executable (current Python interpreter)
        - {workspace} - Replaced with session directory
        - {sre_tools} - Replaced with path to sre_tools package
        
        Returns:
            TOML configuration string for MCP servers.
        """
        if not self.enabled_tools:
            return ""
        
        tools_config = self._tools_manifest.get("tools", {})
        mcp_section = "\n# MCP Servers (enabled tools)\n"
        
        # Get paths for placeholder resolution
        python_executable = sys.executable
        sre_tools_path = str(Path(__file__).parent.parent / "sre_tools")
        workspace_path = str(Path(self.session_dir).resolve())
        
        for tool_name in self.enabled_tools:
            if tool_name not in tools_config:
                print(f"Warning: Tool '{tool_name}' not found in manifest, skipping", file=sys.stderr)
                continue
            
            tool = tools_config[tool_name]
            tool_type = tool.get("type", "stdio")
            
            mcp_section += f"\n[mcp_servers.{tool_name}]\n"
            
            if tool_type == "stdio":
                # Command-line MCP server
                command = tool.get("command", "python")
                args = list(tool.get("args", []))
                cwd = tool.get("cwd", "")
                env = dict(tool.get("env", {}))
                env_vars = list(tool.get("env_vars", []))
                
                # Resolve {python} placeholder in command
                if command == "{python}" or command == "python":
                    command = python_executable
                
                # Resolve placeholders in args
                args = [
                    arg.replace("{python}", python_executable)
                       .replace("{workspace}", workspace_path)
                       .replace("{sre_tools}", sre_tools_path)
                    for arg in args
                ]
                
                # For local Python MCP servers, ensure PYTHONPATH includes sre_tools parent
                # This ensures `python -m sre_tools.cli.xxx` can find the module
                if "sre_tools" in " ".join(args):
                    sre_tools_parent = str(Path(__file__).parent.parent)
                    if "PYTHONPATH" not in env:
                        env["PYTHONPATH"] = sre_tools_parent
                    else:
                        env["PYTHONPATH"] = f"{sre_tools_parent}:{env['PYTHONPATH']}"
                
                mcp_section += f'command = "{command}"\n'
                
                if args:
                    # Format args as TOML array
                    args_str = ", ".join(f'"{a}"' for a in args)
                    mcp_section += f'args = [{args_str}]\n'
                
                if cwd:
                    # Resolve placeholders in cwd
                    resolved_cwd = cwd.replace("{workspace}", workspace_path).replace("{sre_tools}", sre_tools_path)
                    mcp_section += f'cwd = "{resolved_cwd}"\n'
                
                if env:
                    # Format env as TOML inline table
                    # Escape backslashes for Windows paths
                    env_items = ", ".join(f'"{k}" = "{v.replace(chr(92), chr(92)+chr(92))}"' for k, v in env.items())
                    mcp_section += f'env = {{ {env_items} }}\n'
                
                if env_vars:
                    # Format env_vars as TOML array
                    vars_str = ", ".join(f'"{v}"' for v in env_vars)
                    mcp_section += f'env_vars = [{vars_str}]\n'
                    
            elif tool_type == "http":
                # HTTP MCP server
                url = tool.get("url", "")
                bearer_token_env_var = tool.get("bearer_token_env_var", "")
                http_headers = tool.get("http_headers", {})
                env_http_headers = tool.get("env_http_headers", {})
                
                if url:
                    mcp_section += f'url = "{url}"\n'
                
                if bearer_token_env_var:
                    mcp_section += f'bearer_token_env_var = "{bearer_token_env_var}"\n'
                
                if http_headers:
                    items = ", ".join(f'"{k}" = "{v}"' for k, v in http_headers.items())
                    mcp_section += f'http_headers = {{ {items} }}\n'
                
                if env_http_headers:
                    items = ", ".join(f'"{k}" = "{v}"' for k, v in env_http_headers.items())
                    mcp_section += f'env_http_headers = {{ {items} }}\n'
            
            # Common optional fields
            if "enabled_tools" in tool:
                tools_str = ", ".join(f'"{t}"' for t in tool["enabled_tools"])
                mcp_section += f'enabled_tools = [{tools_str}]\n'
            
            if "disabled_tools" in tool:
                tools_str = ", ".join(f'"{t}"' for t in tool["disabled_tools"])
                mcp_section += f'disabled_tools = [{tools_str}]\n'
            
            if "startup_timeout_sec" in tool:
                mcp_section += f'startup_timeout_sec = {tool["startup_timeout_sec"]}\n'
            
            if "tool_timeout_sec" in tool:
                mcp_section += f'tool_timeout_sec = {tool["tool_timeout_sec"]}\n'
        
        return mcp_section

    def _generate_config_toml(self, prompt_path: str) -> str:
        """Generate config.toml content with proper path resolution."""
        # Get provider configuration from dynamic providers
        provider_config = self.model_providers.get(self.model_provider, {})
        base_url = self.api_base_url or provider_config.get("base_url", "")
        env_key = self.api_key_env or provider_config.get("env_key", "OPENAI_API_KEY")
        wire_api = provider_config.get("wire_api", "chat")
        
        # Session directory is the only writable root
        session_path = str(Path(self.session_dir).resolve())
        writable_roots_str = f'"{session_path}"'
        
        # Approval policy depends on full_auto mode
        # Valid values: "untrusted", "on-failure", "on-request", "never"
        # "never" = auto-approve all (full-auto mode)
        # "on-failure" = run commands, ask for approval if they fail (interactive)
        approval_policy = "never" if self.full_auto else "on-failure"

        # Build OTEL section (must be at ROOT level, before profiles)
        otel_section = ""
        if self.collect_traces:
            otel_endpoint = f"http://localhost:{self.otel_port}/v1/logs"
            otel_section = f'''
# OpenTelemetry Configuration (Auto-configured for trace collection)
# IMPORTANT: [otel] must be at root level, NOT inside a profile
[otel]
environment = "dev"
log_user_prompt = true
exporter = {{ otlp-http = {{ endpoint = "{otel_endpoint}", protocol = "binary" }} }}
'''

        # Build MCP Servers section (for enabled tools)
        mcp_servers_section = self._generate_mcp_servers_section()

        # Build Model Providers section
        providers_section = ""
        for name, cfg in self.model_providers.items():
            providers_section += f'\n[model_providers.{name}]\n'
            for k, v in cfg.items():
                if isinstance(v, str):
                    providers_section += f'{k} = "{v}"\n'
                elif isinstance(v, dict):
                    items = []
                    for subk, subv in v.items():
                        if isinstance(subv, str):
                            items.append(f'{subk} = "{subv}"')
                        else:
                            items.append(f'{subk} = {subv}')
                    providers_section += f'{k} = {{ {", ".join(items)} }}\n'
                elif isinstance(v, bool):
                    providers_section += f'{k} = {str(v).lower()}\n'
                else:
                    providers_section += f'{k} = {v}\n'

        config = f'''# Zero Configuration (Auto-generated)
# Generated for profile: {self.profile}

# Set the default profile
profile = "{self.profile}"

# Show raw reasoning content (chain-of-thought) when available
# This surfaces the model's internal thinking in OTEL traces
show_raw_agent_reasoning = true

# Enable history persistence - save all session data
[history]
persistence = "save-all"
{otel_section}
# {self.profile} Profile
[profiles.{self.profile}]

# Model configuration
model = "{self.model}"
model_provider = "{self.model_provider}"

# Reasoning configuration
model_reasoning_effort = "{self.reasoning_effort}"
model_reasoning_summary = "{self.reasoning_summary}"

# Custom instructions file (absolute path for portability)
experimental_instructions_file = "{prompt_path}"

# Sandbox policy - workspace-write with writable_roots for session directory
sandbox_mode = "{self.sandbox_mode}"

# Approval policy - depends on full_auto mode
# "never" = auto-approve all actions (full-auto mode)
# "on-failure" = run commands, prompt if they fail (interactive mode)
approval_policy = "{approval_policy}"

# Root-level writable roots (session directory)
[sandbox_workspace_write]
writable_roots = [
    {writable_roots_str}
]

# Writable directories for sandbox (allows writing to session directory)
[profiles.{self.profile}.sandbox_workspace_write]
writable_roots = [
    {writable_roots_str}
]

# Model provider configuration (merged from agent.toml)
{providers_section}
{mcp_servers_section}'''

        return config

    def get_output_path(self) -> str:
        """Get the full ABSOLUTE output path in session directory.
        
        Output is written to session_dir/output.json.
        """
        return str((Path(self.session_dir) / "output.json").resolve())

    def get_traces_output_path(self) -> str:
        """Get the traces output path in session directory."""
        return str((Path(self.session_dir) / "traces" / "traces.jsonl").resolve())

    def get_query(self) -> str:
        """Get the query with placeholders substituted."""
        output_path = self.get_output_path()
        
        # Format snapshot directories as comma-separated absolute paths
        if self.read_only_dirs:
            snapshot_dirs = ", ".join([str(Path(d).resolve()) for d in self.read_only_dirs])
        else:
            snapshot_dirs = "(no snapshot directories provided)"
        
        return self.query_template.format(
            output_path=output_path,
            snapshot_dirs=snapshot_dirs
        )

    def cleanup(self) -> None:
        """Clean up temporary resources."""
        if self._temp_config_dir:
            self._temp_config_dir.cleanup()
            self._temp_config_dir = None

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()
