"""
MCP tool definitions and handlers for logs module.
"""

from typing import Any

from mcp.types import TextContent, Tool

from .analyzer import _log_analysis


def get_tool_definitions() -> list[Tool]:
    """Return MCP tool definitions for logs tools.

    Note: Tool definitions are extracted from the original tools.py
    and should be kept in sync with the README documentation.
    """
    # TODO: Extract tool definitions from original tools.py (lines 44-688)
    # For now, import them from a shared location
    from ..tool_registry import get_tools_for_module

    return get_tools_for_module("logs")


def get_handlers() -> dict[str, callable]:
    """Return mapping of tool names to handler functions."""
    return {
        "log_analysis": _log_analysis,
    }
