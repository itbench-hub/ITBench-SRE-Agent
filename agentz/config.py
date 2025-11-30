"""
Configuration management for Agentz.

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
BUNDLED_PROMPT_PATH = Path(__file__).parent / "agentz-config" / "prompts" / "sre_support_engineer.md"

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
class AgentZConfig:
    """Configuration for Agentz execution."""

    # Model configuration
    model: str = "anthropic/claude-opus-4.5"
    model_provider: str = "openrouter"
    reasoning_effort: str = "high"
    reasoning_summary: str = "detailed"

    # API configuration
    api_key_env: str | None = None
    api_base_url: str | None = None

    # Paths
    config_dir: str | None = None
    prompt_file: str | None = None
    policy_file: str | None = None

    # Output configuration
    output_dir: str = "/tmp/agentz-output/reports"
    run_id: str = "1"

    # Execution options
    profile: str = "sre_support_engineer"
    full_auto: bool = True
    sandbox_mode: str = "workspace-write"
    network_access: bool = False
    writable_roots: list[str] = field(default_factory=lambda: ["/tmp/agentz-output"])

    # Query template
    query_template: str = "analyze the incident snapshot in this directory. Write the agent_output.json file at {output_path}"

    # Verbose mode
    verbose: bool = False

    # Tracing configuration
    collect_traces: bool = False
    traces_output_dir: str | None = None
    otel_port: int = 4318
    
    # Dynamic providers loaded from agent.toml
    model_providers: dict = field(default_factory=lambda: PROVIDER_CONFIGS.copy())

    # Internal state
    _temp_config_dir: tempfile.TemporaryDirectory | None = field(default=None, repr=False)

    @classmethod
    def from_args(cls, args: Any) -> "AgentZConfig":
        """Create configuration from parsed command-line arguments."""
        # Load agent.toml
        agent_toml_path = Path(__file__).parent / "agentz-config" / "agent.toml"
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
        # Check CLI args namespace for profile, but handle if it's not present (some callers might not set it)
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
            # Auto-detect based on provider
            provider_config = all_providers.get(model_provider, {})
            api_key_env = provider_config.get("env_key")

        # Build writable roots list
        # Default roots from profile + CLI roots
        profile_writable_roots = profile_data.get("sandbox_workspace_write", {}).get("writable_roots", [])
        writable_roots = ["/tmp/agentz-output", args.output_dir]
        writable_roots.extend(profile_writable_roots)
        writable_roots.extend(args.writable_root)

        # Determine traces output directory
        traces_output_dir = getattr(args, "traces_output_dir", None)
        if not traces_output_dir and getattr(args, "collect_traces", False):
            traces_output_dir = str(Path(args.output_dir) / "traces")

        return cls(
            model=model,
            model_provider=model_provider,
            reasoning_effort=getattr(args, "reasoning_effort", "high"),
            api_key_env=api_key_env,
            api_base_url=getattr(args, "api_base_url", None),
            config_dir=getattr(args, "config_dir", None),
            prompt_file=getattr(args, "prompt_file", None),
            policy_file=getattr(args, "policy_file", None),
            output_dir=args.output_dir,
            run_id=args.run_id,
            profile=profile,
            full_auto=getattr(args, "full_auto", True),
            sandbox_mode=getattr(args, "sandbox_mode", "workspace-write"),
            network_access=getattr(args, "network_access", False),
            writable_roots=list(set(writable_roots)),  # Deduplicate
            query_template=getattr(args, "query", "analyze the incident snapshot in this directory. Write the agent_output.json file at {output_path}"),
            verbose=getattr(args, "verbose", False),
            collect_traces=getattr(args, "collect_traces", False),
            traces_output_dir=traces_output_dir,
            otel_port=getattr(args, "otel_port", 4318),
            model_providers=all_providers,
        )

    def get_effective_config_dir(self) -> str:
        """Get the effective configuration directory, creating a temp one if needed.
        
        When trace collection is enabled, we always generate a temp config
        to ensure the OTEL settings are correctly configured for the otel-cli server.
        """
        # When collecting traces, always generate config with correct OTEL settings
        if self.collect_traces:
            return self._create_temp_config_dir()

        if self.config_dir:
            config_path = Path(self.config_dir)
            if config_path.exists():
                return str(config_path.resolve())
            raise FileNotFoundError(f"Config directory not found: {self.config_dir}")

        # Check for bundled config in the package
        bundled_config = Path(__file__).parent / "agentz-config"
        if bundled_config.exists():
            return str(bundled_config.resolve())

        # Generate a temporary configuration directory
        return self._create_temp_config_dir()

    def _create_temp_config_dir(self) -> str:
        """Create a temporary configuration directory with generated config files."""
        self._temp_config_dir = tempfile.TemporaryDirectory(prefix="agentz-config-")
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
        Supports variable substitution for {output_path}.
        """
        # Use custom prompt file if specified, otherwise bundled
        prompt_path = Path(self.prompt_file) if self.prompt_file else BUNDLED_PROMPT_PATH
        
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        
        content = prompt_path.read_text()
        
        # Template substitution
        output_path = self.get_output_path()
        content = content.replace("{output_path}", output_path)
            
        return content

    def _get_policy_content(self) -> str:
        """Get policy content from file or return default."""
        if self.policy_file:
            policy_path = Path(self.policy_file)
            if policy_path.exists():
                return policy_path.read_text()
            raise FileNotFoundError(f"Policy file not found: {self.policy_file}")
        return DEFAULT_POLICY

    def get_all_writable_roots(self) -> list[str]:
        """Get all writable roots as absolute paths."""
        all_writable_roots = set()
        all_writable_roots.add(str(Path(self.output_dir).resolve()))
        all_writable_roots.add("/tmp/agentz-output")
        for root in self.writable_roots:
            all_writable_roots.add(str(Path(root).resolve()))
        return sorted(list(all_writable_roots))

    def _generate_config_toml(self, prompt_path: str) -> str:
        """Generate config.toml content with proper path resolution."""
        # Get provider configuration from dynamic providers
        provider_config = self.model_providers.get(self.model_provider, {})
        base_url = self.api_base_url or provider_config.get("base_url", "")
        env_key = self.api_key_env or provider_config.get("env_key", "OPENAI_API_KEY")
        wire_api = provider_config.get("wire_api", "chat")
        
        # Get writable roots
        writable_roots = self.get_all_writable_roots()
        # Format as TOML array
        writable_roots_str = ',\n    '.join(f'"{p}"' for p in writable_roots)

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

        # Build Model Providers section
        # We'll re-serialize the providers from our merged list
        providers_section = ""
        for name, cfg in self.model_providers.items():
            providers_section += f'\n[model_providers.{name}]\n'
            for k, v in cfg.items():
                if isinstance(v, str):
                    providers_section += f'{k} = "{v}"\n'
                elif isinstance(v, dict):
                    # Convert to TOML inline table
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

        config = f'''# Agentz Configuration (Auto-generated)
# Generated for profile: {self.profile}

# Set the default profile
profile = "{self.profile}"

# Show raw reasoning content (chain-of-thought) when available
# This surfaces the model's internal thinking in OTEL traces
show_raw_agent_reasoning = true
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

# Sandbox policy - workspace-write with writable_roots for output directory
sandbox_mode = "{self.sandbox_mode}"

# Root-level writable roots (safeguard)
[sandbox_workspace_write]
writable_roots = [
    {writable_roots_str}
]

# Approval policy - execution policy (.codexpolicy) controls what's allowed
approval_policy = "never"

# Writable directories for sandbox (allows writing agent output)
[profiles.{self.profile}.sandbox_workspace_write]
writable_roots = [
    {writable_roots_str}
]

# Model provider configuration (merged from agent.toml)
{providers_section}
'''

        return config

    def get_output_path(self) -> str:
        """Get the full ABSOLUTE output path.
        
        Must be absolute because the agent runs with cwd=scenario_dir,
        and the path must match writable_roots which are absolute.
        """
        return str((Path(self.output_dir) / "agent_output.json").resolve())

    def get_traces_output_path(self) -> str:
        """Get the traces output path (absolute)."""
        if self.traces_output_dir:
            return str((Path(self.traces_output_dir) / "traces.jsonl").resolve())
        return str((Path(self.output_dir) / "traces.jsonl").resolve())

    def get_query(self) -> str:
        """Get the query with output path substituted."""
        output_path = self.get_output_path()
        return self.query_template.format(output_path=output_path)

    def cleanup(self) -> None:
        """Clean up temporary resources."""
        if self._temp_config_dir:
            self._temp_config_dir.cleanup()
            self._temp_config_dir = None

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()

