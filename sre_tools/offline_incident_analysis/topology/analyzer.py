"""
Analysis implementation.
"""

import ast
import csv
import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import numpy as np
    import pandas as pd
except ImportError:
    pd = None
    np = None

try:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig
except ImportError:
    TemplateMiner = None
    TemplateMinerConfig = None
    MaskingInstruction = None

from mcp.types import TextContent, Tool

from sre_tools.utils import format_timestamp, read_json_file, read_tsv_file, truncate_string


async def _topology_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze operational topology - shows ALL relationships for an entity.

    Returns unified view containing:
    1. Entity metadata (kind, name, namespace, aliases)
    2. Direct relationships (explicit edges)
    3. Relationships by type (grouped)
    4. Backing infrastructure (Namespace -> Deployment -> ReplicaSet -> Pod)
    5. Callers/callees (who calls this, what this calls)
    6. Call chains to root and leaf services
    7. Infrastructure dependencies (pods/deployments using this service)
    """
    topology_file = args.get("topology_file", "")
    entity = args.get("entity", "")

    if not entity:
        return [TextContent(type="text", text="Error: 'entity' is required")]

    topo_path = Path(topology_file)
    if not topo_path.exists():
        return [
            TextContent(
                type="text",
                text=f"Error: Topology file not found: {topology_file}. " f"Build it first with build_topology tool.",
            )
        ]

    try:
        topology = json.loads(topo_path.read_text())
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading topology: {e}")]

    nodes = topology.get("nodes", [])
    edges = topology.get("edges", [])

    # Build lookup structures
    nodes_by_id = {n["id"]: n for n in nodes}

    # Adjacency lists
    outgoing: dict[str, list[tuple[str, str, dict]]] = {}
    incoming: dict[str, list[tuple[str, str, dict]]] = {}

    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        rel = edge.get("relation", "")
        meta = edge.get("metadata", {})
        outgoing.setdefault(src, []).append((tgt, rel, meta))
        incoming.setdefault(tgt, []).append((src, rel, meta))

    def find_node(query: str) -> Optional[str]:
        """Find node by ID (Kind/name) or just name."""
        # Exact ID match (Kind/name format)
        if query in nodes_by_id:
            return query

        # Case-insensitive ID match
        query_lower = query.lower()
        for node_id in nodes_by_id:
            if node_id.lower() == query_lower:
                return node_id

        # Match by name only - prefer App/Service
        priority_kinds = ["App", "Service", "Deployment", "Pod", "ReplicaSet"]
        for kind in priority_kinds:
            for node in nodes:
                if node.get("name", "").lower() == query_lower and node.get("kind") == kind:
                    return node["id"]

        # Any name match
        for node in nodes:
            if node.get("name", "").lower() == query_lower:
                return node["id"]

        # Partial match
        for node_id in nodes_by_id:
            if query_lower in node_id.lower():
                return node_id

        return None

    def get_aliases(node_id: str) -> set[str]:
        aliases = {node_id}
        for tgt, rel, _ in outgoing.get(node_id, []):
            if rel == "is_alias":
                aliases.add(tgt)
        for src, rel, _ in incoming.get(node_id, []):
            if rel == "is_alias":
                aliases.add(src)
        return aliases

    def get_name(node_id: str) -> str:
        """Get just the name from a node."""
        return nodes_by_id.get(node_id, {}).get("name", node_id)

    # Find the entity
    start_node = find_node(entity)
    if not start_node:
        available = [n for n in nodes_by_id.keys() if nodes_by_id[n].get("kind") in ["App", "Service", "Pod"]][:20]
        return [TextContent(type="text", text=f"Error: Entity '{entity}' not found. Some available: {available}")]

    aliases = get_aliases(start_node)
    node_info = nodes_by_id.get(start_node, {})

    # Build alias map for call graph normalization (Service -> App)
    alias_map: dict[str, str] = {}
    for src, targets in outgoing.items():
        for tgt, rel, _ in targets:
            if rel == "is_alias":
                alias_map[tgt] = src

    def normalize(node: str) -> str:
        """Normalize to canonical App name."""
        return alias_map.get(node, node)

    # ========== BUILD UNIFIED RESULT ==========
    result: dict[str, Any] = {
        "entity": get_name(start_node),
        "kind": node_info.get("kind"),
        "name": node_info.get("name"),
        "namespace": node_info.get("namespace"),
        "aliases": sorted([a for a in aliases if a != start_node]),
    }

    # ========== 1. DIRECT RELATIONSHIPS ==========
    direct_rels = []
    for node_id in aliases:
        my_kind = nodes_by_id.get(node_id, {}).get("kind", "")
        my_name = nodes_by_id.get(node_id, {}).get("name", node_id)

        for tgt, rel, _ in outgoing.get(node_id, []):
            tgt_kind = nodes_by_id.get(tgt, {}).get("kind", "")
            tgt_name = nodes_by_id.get(tgt, {}).get("name", tgt)
            direct_rels.append(f"{my_kind}/{my_name} --{rel}--> {tgt_kind}/{tgt_name}")

        for src, rel, _ in incoming.get(node_id, []):
            src_kind = nodes_by_id.get(src, {}).get("kind", "")
            src_name = nodes_by_id.get(src, {}).get("name", src)
            direct_rels.append(f"{src_kind}/{src_name} --{rel}--> {my_kind}/{my_name}")

    result["direct_relationships"] = sorted(set(direct_rels))

    # ========== 2. RELATIONSHIPS BY TYPE ==========
    by_type: dict[str, list[str]] = {}
    for node_id in aliases:
        for tgt, rel, _ in outgoing.get(node_id, []):
            tgt_kind = nodes_by_id.get(tgt, {}).get("kind", "")
            tgt_name = nodes_by_id.get(tgt, {}).get("name", tgt)
            by_type.setdefault(f"--{rel}-->", []).append(f"{tgt_kind}/{tgt_name}")

        for src, rel, _ in incoming.get(node_id, []):
            src_kind = nodes_by_id.get(src, {}).get("kind", "")
            src_name = nodes_by_id.get(src, {}).get("name", src)
            by_type.setdefault(f"<--{rel}--", []).append(f"{src_kind}/{src_name}")

    result["relationships_by_type"] = {k: sorted(set(v)) for k, v in by_type.items()}

    # ========== 3. BACKING INFRASTRUCTURE ==========
    # Find infrastructure chain: Namespace -> Deployment -> ReplicaSet -> Pod
    infra_chain: list[str] = []

    if node_info.get("kind") in ["App", "Service"]:
        # Find the service alias if we're starting from App
        service_node = None
        for alias in aliases:
            if nodes_by_id.get(alias, {}).get("kind") == "Service":
                service_node = alias
                break

        if service_node:
            service_name = nodes_by_id.get(service_node, {}).get("name", "")
            namespace = nodes_by_id.get(service_node, {}).get("namespace", "")

            # Find Deployment with same name
            deploy_id = f"Deployment/{service_name}"
            if deploy_id not in nodes_by_id:
                # Try namespace-prefixed format
                deploy_id = f"Deployment/{namespace}/{service_name}"

            if deploy_id in nodes_by_id:
                infra_chain.append(f"Namespace/{namespace} --contains--> Deployment/{service_name}")

                for tgt, rel, _ in outgoing.get(deploy_id, []):
                    if rel == "contains" and nodes_by_id.get(tgt, {}).get("kind") == "ReplicaSet":
                        rs_name = nodes_by_id.get(tgt, {}).get("name", tgt)
                        infra_chain.append(f"Deployment/{service_name} --contains--> ReplicaSet/{rs_name}")

                        for pod_tgt, pod_rel, _ in outgoing.get(tgt, []):
                            if pod_rel == "contains" and nodes_by_id.get(pod_tgt, {}).get("kind") == "Pod":
                                pod_name = nodes_by_id.get(pod_tgt, {}).get("name", pod_tgt)
                                infra_chain.append(f"ReplicaSet/{rs_name} --contains--> Pod/{pod_name}")

    if infra_chain:
        result["backing_infrastructure"] = infra_chain

    # ========== 4. CALL GRAPH: CALLERS / CALLEES ==========
    # Build unified call graph using normalized names
    call_graph: dict[str, set[str]] = {}
    reverse_call: dict[str, set[str]] = {}

    for src, targets in outgoing.items():
        for tgt, rel, _ in targets:
            if rel == "calls":
                norm_src = normalize(src)
                norm_tgt = normalize(tgt)
                call_graph.setdefault(norm_src, set()).add(norm_tgt)
                reverse_call.setdefault(norm_tgt, set()).add(norm_src)

    # Also track "infra" dependencies (depends_on from pods to services)
    infra_callers: dict[str, set[str]] = {}  # service -> app names that depend on it
    for src, targets in outgoing.items():
        src_kind = nodes_by_id.get(src, {}).get("kind")
        if src_kind == "Pod":
            # Extract deployment name from pod
            pod_name = nodes_by_id.get(src, {}).get("name", "")
            parts = pod_name.rsplit("-", 2)
            deployment_name = parts[0] if len(parts) >= 3 else pod_name

            for tgt, rel, _ in targets:
                if rel == "depends_on":
                    # Normalize the target service
                    norm_tgt = normalize(tgt)
                    tgt_name = get_name(norm_tgt)
                    infra_callers.setdefault(tgt_name, set()).add(deployment_name)

    norm_aliases = {normalize(a) for a in aliases}
    entity_name = get_name(start_node)

    # Direct callers (via "calls" edge)
    direct_callers: set[str] = set()
    for norm_alias in norm_aliases:
        for caller in reverse_call.get(norm_alias, set()):
            direct_callers.add(get_name(caller))

    # Direct callees (via "calls" edge)
    direct_callees: set[str] = set()
    for norm_alias in norm_aliases:
        for callee in call_graph.get(norm_alias, set()):
            direct_callees.add(get_name(callee))

    # Infrastructure callers (via "depends_on" edge from pods)
    infra_caller_names: set[str] = set()
    for alias in aliases:
        alias_name = get_name(alias)
        if alias_name in infra_callers:
            infra_caller_names.update(infra_callers[alias_name])

    # Combine all callers (both via "calls" and "depends_on")
    all_callers = direct_callers | infra_caller_names

    result["callers"] = sorted(all_callers)
    result["callees"] = sorted(direct_callees)

    # ========== 5. CALL CHAINS ==========
    # Find root services (entry points - no callers in call graph)
    all_in_graph = set(call_graph.keys()) | set(reverse_call.keys())
    root_services = [s for s in all_in_graph if s not in reverse_call or len(reverse_call[s]) == 0]
    leaf_services = [s for s in all_in_graph if s not in call_graph or len(call_graph[s]) == 0]

    # Call chains TO this entity (from roots)
    def find_call_chains_to(targets: set[str], max_depth: int = 10) -> list[str]:
        paths: list[str] = []

        def dfs(current: str, path: list[str], visited: set):
            if len(path) > max_depth:
                return
            if current in targets:
                paths.append(" -> ".join(path))
                return
            for callee in call_graph.get(current, set()):
                if callee not in visited:
                    visited.add(callee)
                    path.append(get_name(callee))
                    dfs(callee, path, visited)
                    path.pop()
                    visited.discard(callee)

        for root in root_services:
            if root in targets:
                paths.append(get_name(root))
            else:
                dfs(root, [get_name(root)], {root})

        return paths

    # Call chains FROM this entity (to leaves)
    def find_call_chains_from(sources: set[str], max_depth: int = 10) -> list[str]:
        paths: list[str] = []

        def dfs(current: str, path: list[str], visited: set):
            if len(path) > max_depth:
                return
            callees = call_graph.get(current, set())
            if not callees or current in leaf_services:
                if len(path) > 1:
                    paths.append(" -> ".join(path))
                return
            for callee in callees:
                if callee not in visited:
                    visited.add(callee)
                    path.append(get_name(callee))
                    dfs(callee, path, visited)
                    path.pop()
                    visited.discard(callee)

        for source in sources:
            dfs(source, [get_name(source)], {source})

        return paths

    # Build chains using normalized aliases
    chains_to = find_call_chains_to(norm_aliases)
    chains_from = find_call_chains_from(norm_aliases)

    # For infra services (not in call graph), also show depends_on paths
    if not chains_to and infra_caller_names:
        # Build "infra" chains: caller -> entity (infra)
        chains_to = [f"{caller} -> {entity_name} (infra)" for caller in sorted(infra_caller_names)]

    result["call_chains_to_root"] = sorted(set(chains_to[:20]))
    result["call_chains_to_leaf"] = sorted(set(chains_from[:20]))

    # ========== 6. INFRASTRUCTURE DEPENDENCIES ==========
    # Pods and deployments that depend on this service (via depends_on edges)
    dependent_pods: set[str] = set()
    for alias in aliases:
        for src, rel, _ in incoming.get(alias, []):
            if rel == "depends_on" and nodes_by_id.get(src, {}).get("kind") == "Pod":
                dependent_pods.add(nodes_by_id.get(src, {}).get("name", src))

    if dependent_pods:
        deployments: set[str] = set()
        for pod_name in dependent_pods:
            parts = pod_name.rsplit("-", 2)
            if len(parts) >= 3:
                deployments.add(parts[0])

        result["used_by_infra"] = {
            "pods": sorted(dependent_pods),
            "deployments": sorted(deployments),
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# =============================================================================
# Helper Functions for Metrics/Events (kept separate)
# =============================================================================
