import fnmatch
import os
from typing import List

import toml
from pydantic import BaseModel, Field


class BlacklistConfig(BaseModel):
    """Configuration for file/directory blacklisting."""

    patterns: List[str] = Field(
        default_factory=list,
        description="List of glob patterns to exclude from file operations (e.g., 'ground_truth*.yaml', '*.secret')",
    )

    def is_blacklisted(self, file_path: str) -> bool:
        """Check if a file path matches any blacklist pattern."""
        # Get just the filename for pattern matching
        filename = os.path.basename(file_path)

        for pattern in self.patterns:
            # Match against filename
            if fnmatch.fnmatch(filename, pattern):
                return True
            # Also match against full path for patterns like "dir/*.yaml"
            if fnmatch.fnmatch(file_path, pattern):
                return True
            # Handle patterns with ** for recursive matching
            if "**" in pattern:
                # Convert ** pattern to work with fnmatch
                parts = pattern.split("**")
                if len(parts) == 2 and parts[0] == "":
                    # Pattern like "**/*.yaml" - match suffix
                    suffix_pattern = parts[1].lstrip("/")
                    if fnmatch.fnmatch(filename, suffix_pattern):
                        return True
        return False


class FileToolsConfig(BaseModel):
    """Configuration for file system operation tools."""

    enabled: bool = Field(default=True, description="Global switch for file tools")
    base_dir: str | None = Field(default=None, description="Restrict file operations to this directory")

    # Fine-grained controls
    enable_read_file: bool = Field(default=True, description="Enable reading files")
    enable_edit_file: bool = Field(default=True, description="Enable editing files")
    enable_create_file: bool = Field(default=True, description="Enable creating new files")
    enable_delete_file: bool = Field(default=False, description="Enable deleting files")  # Default to False for safety
    enable_list_directory: bool = Field(default=True, description="Enable listing directories")


class SearchToolsConfig(BaseModel):
    """Configuration for search tools."""

    enabled: bool = Field(default=True, description="Global switch for search tools")
    max_results: int = Field(default=10, description="Maximum number of search results to return")

    # Fine-grained controls
    enable_grep: bool = Field(default=True, description="Enable regex search (grep)")
    enable_file_search: bool = Field(default=True, description="Enable file name search (glob)")
    enable_codebase_search: bool = Field(default=True, description="Enable semantic codebase search")


class SystemToolsConfig(BaseModel):
    """Configuration for system tools."""

    enabled: bool = Field(default=True, description="Global switch for system tools")

    # Fine-grained controls
    enable_run_terminal_cmd: bool = Field(default=True, description="Enable executing terminal commands")


class LLMConfig(BaseModel):
    """Configuration for LLM provider (OpenAI compatible)."""

    api_key: str | None = Field(default=None, description="API Key for the LLM provider")
    base_url: str | None = Field(
        default=None, description="Base URL for the LLM provider (e.g. https://openrouter.ai/api/v1)"
    )


class AgentConfig(BaseModel):
    """Main configuration for the SRE Agent."""

    model_name: str = Field(default="gpt-4o", description="Model identifier")
    recursion_limit: int = Field(
        default=100, description="Recursion limit for agent execution (each tool call = 2 steps)"
    )
    max_tool_output_length: int = Field(
        default=5000, description="Max characters for tool output when summarization is disabled"
    )

    # LLM Configuration
    llm_config: LLMConfig = Field(default_factory=LLMConfig)

    # Tool configurations
    file_tools: FileToolsConfig = Field(default_factory=FileToolsConfig)
    search_tools: SearchToolsConfig = Field(default_factory=SearchToolsConfig)
    system_tools: SystemToolsConfig = Field(default_factory=SystemToolsConfig)

    # Blacklist configuration
    blacklist: BlacklistConfig = Field(default_factory=BlacklistConfig)

    class Config:
        env_prefix = "SRE_AGENT_"

    @classmethod
    def from_toml(cls, path: str) -> "AgentConfig":
        """Load configuration from a TOML file."""
        with open(path, "r") as f:
            config_data = toml.load(f)
        return cls(**config_data)
