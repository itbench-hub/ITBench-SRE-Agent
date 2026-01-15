"""
MCP tool definitions and handlers for context module.
"""

from typing import Any

from mcp.types import TextContent, Tool

from .aggregator import _find_scenario_files, _get_context_contract
from .cli import _cli_get_context_contract


def get_tool_definitions() -> list[Tool]:
    """Return MCP tool definitions for context tools.

    Note: Tool definitions are extracted from the original tools.py
    and should be kept in sync with the README documentation.
    """
    # TODO: Extract tool definitions from original tools.py (lines 44-688)
    # For now, import them from a shared location
    from ..tool_registry import get_tools_for_module

    return get_tools_for_module("context")


def get_handlers() -> dict[str, callable]:
    """Return mapping of tool names to handler functions."""
    return {
        "get_context_contract": _get_context_contract,
    }


def get_cli_commands() -> dict[str, callable]:
    """Return mapping of CLI command names to handler functions."""
    return {
        "get_context_contract": _cli_get_context_contract,
    }
