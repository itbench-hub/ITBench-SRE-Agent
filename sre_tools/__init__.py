"""
SRE Tools - Modular MCP tools for AI agents.

This package provides reusable MCP (Model Context Protocol) tools that can be
used by Zero or other AI agents for SRE incident investigation.

Tools are defined in manifest.toml and can be enabled selectively via CLI flags.
"""

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib


# Path to the manifest file
MANIFEST_PATH = Path(__file__).parent / "manifest.toml"


def load_manifest(manifest_path: Path | str | None = None) -> dict[str, Any]:
    """Load the tools manifest from a TOML file.
    
    Args:
        manifest_path: Path to manifest.toml. If None, uses the default bundled manifest.
        
    Returns:
        Dictionary containing the manifest data with 'tools' key.
        
    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If the manifest file is invalid.
    """
    path = Path(manifest_path) if manifest_path else MANIFEST_PATH
    
    if not path.exists():
        raise FileNotFoundError(f"Tools manifest not found: {path}")
    
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse manifest {path}: {e}") from e
    
    # Ensure 'tools' key exists
    if "tools" not in data:
        data["tools"] = {}
    
    return data


def get_tool_config(tool_name: str, manifest_path: Path | str | None = None) -> dict[str, Any] | None:
    """Get configuration for a specific tool.
    
    Args:
        tool_name: Name of the tool (e.g., 'sre_utils', 'datadog')
        manifest_path: Optional path to custom manifest.
        
    Returns:
        Tool configuration dictionary, or None if tool not found.
    """
    manifest = load_manifest(manifest_path)
    return manifest.get("tools", {}).get(tool_name)


def list_tools(manifest_path: Path | str | None = None) -> list[dict[str, Any]]:
    """List all available tools from the manifest.
    
    Args:
        manifest_path: Optional path to custom manifest.
        
    Returns:
        List of tool info dictionaries with 'name', 'description', 'type' keys.
    """
    manifest = load_manifest(manifest_path)
    tools = []
    
    for name, config in manifest.get("tools", {}).items():
        tools.append({
            "name": name,
            "description": config.get("description", "No description"),
            "type": config.get("type", "unknown"),
        })
    
    return tools


__all__ = [
    "load_manifest",
    "get_tool_config",
    "list_tools",
    "MANIFEST_PATH",
]




