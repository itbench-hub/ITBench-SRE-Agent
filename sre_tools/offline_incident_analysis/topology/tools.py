"""
MCP tool wrappers and definitions.
"""

from pathlib import Path
from typing import Any

from mcp.types import TextContent

from .builder import build_topology_standalone


async def _build_topology(args: dict[str, Any]) -> list[TextContent]:
    """Build operational topology from architecture and K8s objects."""
    arch_file = args.get("arch_file", "")
    k8s_objects_file = args.get("k8s_objects_file", "")
    output_file = args.get("output_file", "")

    if not output_file:
        return [TextContent(type="text", text="Error: output_file is required")]

    arch_path = Path(arch_file)
    k8s_path = Path(k8s_objects_file)
    output_path = Path(output_file)

    if not arch_path.exists():
        return [TextContent(type="text", text=f"Architecture file not found: {arch_file}")]
    if not k8s_path.exists():
        return [TextContent(type="text", text=f"K8s objects file not found: {k8s_objects_file}")]

    try:
        topology = _do_build_topology(arch_path, k8s_path)
    except Exception as e:
        return [TextContent(type="text", text=f"Error building topology: {e}")]

    # Write to output file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(topology, indent=2))

    # Build summary
    summary = f"Topology written to {output_file}\n\n"
    summary += f"**Nodes:** {len(topology['nodes'])}\n"
    summary += f"**Edges:** {len(topology['edges'])}\n\n"

    # Group nodes by kind
    by_kind: dict[str, int] = {}
    for node in topology["nodes"]:
        kind = node.get("kind", "Unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1

    summary += "## Node Types\n"
    for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
        summary += f"- {kind}: {count}\n"

    # Group edges by relation
    by_relation: dict[str, int] = {}
    for edge in topology["edges"]:
        rel = edge.get("relation", "unknown")
        by_relation[rel] = by_relation.get(rel, 0) + 1

    summary += "\n## Edge Types\n"
    for rel, count in sorted(by_relation.items(), key=lambda x: -x[1]):
        summary += f"- {rel}: {count}\n"

    return [TextContent(type="text", text=summary)]


# =============================================================================
# Topology Analysis Implementation
# =============================================================================
