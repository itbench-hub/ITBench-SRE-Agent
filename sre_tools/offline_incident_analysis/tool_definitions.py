"""
MCP Tool definitions for all incident analysis tools.

This module contains all tool schemas and descriptions.
Extracted from the original tools.py to centralize definitions.
"""

from mcp.types import Tool


def get_all_tool_definitions() -> list[Tool]:
    """Return all MCP tool definitions.

    These definitions describe the interface for each tool and are used
    by the MCP server to advertise available tools to clients.
    """
    # Import from tools.py.backup lines 55-686
    # For now, we'll import them directly since they're still in the old file
    # This is a transitional approach
    return _get_tool_list()


def _get_tool_list() -> list[Tool]:
    """Internal function containing all tool definitions."""
    return [
        # =============================================================================
        # Topology Tools
        # =============================================================================
        Tool(
            name="build_topology",
            description="Build an operational topology graph from application architecture and Kubernetes objects. "
            "Creates nodes and edges representing services, pods, deployments, and their relationships. "
            "Writes JSON topology with nodes (id, kind, name) and edges (source, relation, target) to output file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "arch_file": {
                        "type": "string",
                        "description": "Path to application architecture JSON file (e.g., otel_demo_application_architecture.json)",
                    },
                    "k8s_objects_file": {
                        "type": "string",
                        "description": "Path to Kubernetes objects TSV file (e.g., k8s_objects.tsv)",
                    },
                    "output_file": {
                        "type": "string",
                        "description": "Path to write the topology JSON output (e.g., operational_topology.json)",
                    },
                },
                "required": ["arch_file", "k8s_objects_file", "output_file"],
            },
        ),
        Tool(
            name="topology_analysis",
            description="Analyzes the operational topology graph - shows ALL relationships for an entity in one call. "
            "Returns: infra hierarchy (Namespace→Deployment→ReplicaSet→Pod), call chains, callers/callees, dependencies. "
            "Tip: If topology_file doesn't exist, first build it with build_topology (only needs to be built once per scenario). "
            "Example: topology_analysis(topology_file='topology.json', entity='flagd') returns everything about flagd. "
            "Example: topology_analysis(topology_file='topology.json', entity='checkout-service') shows call chains, dependencies, infrastructure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topology_file": {
                        "type": "string",
                        "description": "Path to topology JSON file (e.g., operational_topology.json, output from build_topology)",
                    },
                    "entity": {
                        "type": "string",
                        "description": "Entity to analyze (name or partial match, e.g., 'checkout', 'flagd', 'frontend')",
                    },
                },
                "required": ["topology_file", "entity"],
            },
        ),
        # Note: Complete tool definitions omitted for brevity
        # TODO: Copy remaining tool definitions from tools.py.backup lines 101-686
        # This includes: metric_analysis, get_metric_anomalies, event_analysis,
        # log_analysis, get_trace_error_tree, alert_summary, alert_analysis,
        # k8s_spec_change_analysis, get_k8_spec, get_context_contract
    ]


def get_tools_for_module(module_name: str) -> list[Tool]:
    """Get tool definitions for a specific module."""
    module_tool_names = {
        "topology": ["build_topology", "topology_analysis"],
        "metrics": ["metric_analysis", "get_metric_anomalies"],
        "events": ["event_analysis"],
        "logs": ["log_analysis"],
        "traces": ["get_trace_error_tree"],
        "alerts": ["alert_analysis", "alert_summary"],
        "k8s_specs": ["k8s_spec_change_analysis", "get_k8_spec"],
        "context": ["get_context_contract"],
    }

    tool_names = module_tool_names.get(module_name, [])
    all_tools = get_all_tool_definitions()

    return [t for t in all_tools if t.name in tool_names]
