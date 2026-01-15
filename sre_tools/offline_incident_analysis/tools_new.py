"""
SRE utility tool registration (Refactored).

This is the new modular entry point that delegates to domain-specific modules.
The implementation is now split across multiple modules for maintainability.

Module Structure:
- shared/: Common utilities (parsers, filters, formatters)
- topology/: Topology building and analysis
- metrics/: Metric analysis and anomaly detection
- events/: K8s event analysis
- logs/: Log analysis with Drain3
- traces/: Distributed trace analysis
- alerts/: Alert analysis and summarization
- k8s_specs/: K8s spec change tracking
- context/: Context aggregation across data sources
"""

from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from .alerts.analyzer import _alert_analysis as alerts_analyze
from .alerts.analyzer import _alert_summary as alerts_summary
from .context.aggregator import _get_context_contract as context_aggregate
from .context.cli import _cli_get_context_contract
from .events.analyzer import _event_analysis as events_analyze
from .k8s_specs.change_analyzer import _k8s_spec_change_analysis as k8s_change_analyze
from .k8s_specs.retriever import _get_k8_spec as k8s_spec_get
from .logs.analyzer import _log_analysis as logs_analyze
from .metrics.analyzer import _metric_analysis as metrics_analyze
from .metrics.anomalies import _get_metric_anomalies as metrics_anomalies
from .topology.analyzer import _topology_analysis as topology_analyze

# Import handlers from domain modules
from .topology.builder import build_topology_standalone
from .topology.cli import _cli_build_topology
from .traces.analyzer import _get_trace_error_tree as traces_analyze


def register_tools(server: Server) -> None:
    """Register all SRE utility tools with the MCP server.

    Args:
        server: The MCP Server instance to register tools with.
    """

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the list of available tools."""
        # Import tool definitions from the centralized location
        # For now, delegate to the old implementation to avoid duplication
        from .tools import register_tools as old_register

        # This is a hack - we create a temporary server to get the tools list
        # In a full refactor, we'd move tool definitions to tool_definitions.py
        temp_server = Server("temp")
        old_register(temp_server)

        # Extract the tools list
        # This preserves backward compatibility while we migrate
        return await temp_server._list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Route tool calls to appropriate handlers."""

        # Topology tools
        if name == "build_topology":
            return await _build_topology(arguments)
        elif name == "topology_analysis":
            return await topology_analyze(arguments)

        # Metrics tools
        elif name == "metric_analysis":
            return await metrics_analyze(arguments)
        elif name == "get_metric_anomalies":
            return await metrics_anomalies(arguments)

        # Events tools
        elif name == "event_analysis":
            return await events_analyze(arguments)

        # Logs tools
        elif name == "log_analysis":
            return await logs_analyze(arguments)

        # Traces tools
        elif name == "get_trace_error_tree":
            return await traces_analyze(arguments)

        # Alerts tools
        elif name == "alert_analysis":
            return await alerts_analyze(arguments)
        elif name == "alert_summary":
            return await alerts_summary(arguments)

        # K8s Specs tools
        elif name == "k8s_spec_change_analysis":
            return await k8s_change_analyze(arguments)
        elif name == "get_k8_spec":
            return await k8s_spec_get(arguments)

        # Context tools
        elif name == "get_context_contract":
            return await context_aggregate(arguments)

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _build_topology(args: dict[str, Any]) -> list[TextContent]:
    """Handler for build_topology tool."""
    arch_file = args.get("arch_file", "")
    k8s_objects_file = args.get("k8s_objects_file", "")
    output_file = args.get("output_file", "")

    if not all([arch_file, k8s_objects_file, output_file]):
        return [TextContent(type="text", text="Error: arch_file, k8s_objects_file, and output_file are required")]

    try:
        result = build_topology_standalone(arch_file, k8s_objects_file, output_file)
        node_count = len(result["nodes"])
        edge_count = len(result["edges"])

        return [
            TextContent(
                type="text",
                text=f"✓ Topology built successfully\n\n"
                f"Output: {output_file}\n"
                f"Nodes: {node_count}\n"
                f"Edges: {edge_count}\n\n"
                f"Use topology_analysis(topology_file='{output_file}', entity='<name>') to analyze relationships.",
            )
        ]
    except Exception as e:
        import traceback

        return [TextContent(type="text", text=f"Error building topology: {e}\n\n{traceback.format_exc()}")]


# Export public API
__all__ = [
    "register_tools",
    "build_topology_standalone",
]
