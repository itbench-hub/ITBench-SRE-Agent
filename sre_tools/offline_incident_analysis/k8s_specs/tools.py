"""
MCP tool definitions and handlers for k8s_specs module.
"""

from typing import Any

from mcp.types import TextContent, Tool

from .change_analyzer import _k8s_spec_change_analysis
from .retriever import _get_k8_spec


def get_tool_definitions() -> list[Tool]:
    """Return MCP tool definitions for k8s_specs tools.

    Note: Tool definitions are extracted from the original tools.py
    and should be kept in sync with the README documentation.
    """
    # TODO: Extract tool definitions from original tools.py (lines 44-688)
    # For now, import them from a shared location
    from ..tool_registry import get_tools_for_module

    return get_tools_for_module("k8s_specs")


def get_handlers() -> dict[str, callable]:
    """Return mapping of tool names to handler functions."""
    return {
        "k8s_spec_change_analysis": _k8s_spec_change_analysis,
        "get_k8_spec": _get_k8_spec,
    }
