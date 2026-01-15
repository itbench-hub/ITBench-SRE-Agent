"""
MCP tool definitions and handlers for metrics module.
"""

from typing import Any

from mcp.types import TextContent, Tool

from .analyzer import _metric_analysis
from .anomalies import _get_metric_anomalies


def get_tool_definitions() -> list[Tool]:
    """Return MCP tool definitions for metrics tools.

    Note: Tool definitions are extracted from the original tools.py
    and should be kept in sync with the README documentation.
    """
    # TODO: Extract tool definitions from original tools.py (lines 44-688)
    # For now, import them from a shared location
    from ..tool_registry import get_tools_for_module

    return get_tools_for_module("metrics")


def get_handlers() -> dict[str, callable]:
    """Return mapping of tool names to handler functions."""
    return {
        "metric_analysis": _metric_analysis,
        "get_metric_anomalies": _get_metric_anomalies,
    }
