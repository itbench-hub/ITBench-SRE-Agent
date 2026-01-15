"""
MCP tool definitions and handlers for traces module.
"""

from typing import Any

from mcp.types import TextContent, Tool

from .analyzer import _get_trace_error_tree


def get_tool_definitions() -> list[Tool]:
    """Return MCP tool definitions for traces tools.

    Note: Tool definitions are extracted from the original tools.py
    and should be kept in sync with the README documentation.
    """
    # TODO: Extract tool definitions from original tools.py (lines 44-688)
    # For now, import them from a shared location
    from ..tool_registry import get_tools_for_module

    return get_tools_for_module("traces")


def get_handlers() -> dict[str, callable]:
    """Return mapping of tool names to handler functions."""
    return {
        "get_trace_error_tree": _get_trace_error_tree,
    }
