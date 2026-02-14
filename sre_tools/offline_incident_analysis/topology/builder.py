"""
Topology graph builder implementation.
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

from ..shared import _obj_id


class _TopologyBuilder:
    """Helper class to build topology graphs with deduplication."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.node_ids: set[str] = set()
        self.edge_ids: set[tuple] = set()

    def add_node(self, node: dict[str, Any]) -> None:
        nid = node["id"]
        if nid not in self.node_ids:
            self.node_ids.add(nid)
            self.nodes.append(node)

    def _edge_key(self, source: str, relation: str, target: str, meta: Optional[dict[str, Any]]) -> tuple:
        meta_tuple = tuple(sorted(meta.items())) if meta else None
        return (source, relation, target, meta_tuple)

    def add_edge(self, source: str, relation: str, target: str, meta: Optional[dict[str, Any]] = None) -> None:
        key = self._edge_key(source, relation, target, meta)
        if key not in self.edge_ids:
            self.edge_ids.add(key)
            edge = {"source": source, "relation": relation, "target": target}
            if meta:
                edge["meta"] = meta
            self.edges.append(edge)


def _load_k8s_objects_for_topology(path: Path) -> list[dict[str, Any]]:
    """Load K8s objects from TSV file with body parsing."""
    # Increase CSV field size limit for large K8s object bodies (e.g., ConfigMaps, Secrets)
    csv.field_size_limit(10 * 1024 * 1024)  # 10MB limit
    rows = list(csv.DictReader(path.read_text().splitlines(), delimiter="\t"))
    objs = []
    for row in rows:
        body = json.loads(row.get("body", "{}"))
        objs.append({**row, "body": body})
    return objs


def _do_build_topology(arch_path: Path, k8s_path: Path) -> dict[str, Any]:
    """Build operational topology from architecture and K8s objects."""
    builder = _TopologyBuilder()
    arch = json.loads(arch_path.read_text())
    k8s_objs = _load_k8s_objects_for_topology(k8s_path)

    objects_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for obj in k8s_objs:
        kind = obj.get("object_kind", "")
        name = obj.get("object_name", "")
        ns = obj.get("namespace") or ("default" if kind != "Namespace" else name)
        objects_by_key[(kind, ns, name)] = obj

    # Add namespaces
    namespaces = set()
    for obj in k8s_objs:
        ns = obj.get("namespace")
        if ns:
            namespaces.add(ns)
        if obj.get("object_kind") == "Namespace":
            namespaces.add(obj.get("object_name"))
    for ns in namespaces:
        builder.add_node({"id": f"Namespace/{ns}", "kind": "Namespace", "name": ns})

    # Add all K8s objects as nodes
    for obj in k8s_objs:
        kind = obj.get("object_kind", "")
        name = obj.get("object_name", "")
        ns = obj.get("namespace") if obj.get("namespace") else ("default" if kind != "Namespace" else name)
        builder.add_node({"id": _obj_id(kind, name, ns), "kind": kind, "name": name, "namespace": ns})

    # Add Node nodes from pod.spec.nodeName
    for obj in k8s_objs:
        if obj.get("object_kind") == "Pod":
            node_name = obj.get("body", {}).get("spec", {}).get("nodeName")
            if node_name:
                builder.add_node({"id": f"Node/{node_name}", "kind": "Node", "name": node_name})

    # Map Services for alias lookups
    services: dict[str, dict[str, str]] = {}
    for obj in k8s_objs:
        if obj.get("object_kind") == "Service":
            ns = obj.get("namespace") or "default"
            services.setdefault(ns, {})[obj.get("object_name")] = _obj_id("Service", obj.get("object_name"), ns)

    # Namespace contains objects
    for obj in k8s_objs:
        ns = obj.get("namespace")
        if ns:
            builder.add_edge(f"Namespace/{ns}", "contains", _obj_id(obj.get("object_kind"), obj.get("object_name")))

    # Owner references
    for obj in k8s_objs:
        metadata = obj.get("body", {}).get("metadata", {})
        owners = metadata.get("ownerReferences", []) or []
        child_id = _obj_id(
            obj.get("object_kind"),
            obj.get("object_name"),
            obj.get("namespace") or ("default" if obj.get("object_kind") != "Namespace" else obj.get("object_name")),
        )
        for ref in owners:
            owner_ns = obj.get("namespace") if ref.get("kind") not in ["Node", "Namespace"] else None
            owner_id = _obj_id(ref.get("kind"), ref.get("name"), owner_ns or obj.get("namespace") or "default")
            builder.add_edge(owner_id, "contains", child_id)

    # Service -> Endpoints
    for obj in k8s_objs:
        if obj.get("object_kind") == "Service":
            ns = obj.get("namespace") or "default"
            sid = _obj_id("Service", obj.get("object_name"), ns)
            ep_key = ("Endpoints", ns, obj.get("object_name"))
            if ep_key in objects_by_key:
                builder.add_edge(sid, "contains", _obj_id("Endpoints", obj.get("object_name"), ns))

    # Endpoints -> Pod via targetRef
    for obj in k8s_objs:
        if obj.get("object_kind") == "Endpoints":
            ns = obj.get("namespace") or "default"
            eid = _obj_id("Endpoints", obj.get("object_name"), ns)
            subsets = obj.get("body", {}).get("subsets", []) or []
            for subset in subsets:
                addresses = (subset.get("addresses") or []) + (subset.get("notReadyAddresses") or [])
                for addr in addresses:
                    tref = addr.get("targetRef") or {}
                    if tref.get("kind") == "Pod":
                        pid = _obj_id("Pod", tref.get("name"), ns)
                        builder.add_edge(eid, "contains", pid)

    # Node -> Pod placement
    for obj in k8s_objs:
        if obj.get("object_kind") == "Pod":
            ns = obj.get("namespace") or "default"
            pid = _obj_id("Pod", obj.get("object_name"), ns)
            node_name = obj.get("body", {}).get("spec", {}).get("nodeName")
            if node_name:
                builder.add_edge(f"Node/{node_name}", "contains", pid)

    # Pod dependencies (service accounts, volumes, env refs)
    telemetry_services = ["otel-collector", "flagd", "kafka", "valkey-cart", "postgresql"]
    for obj in k8s_objs:
        if obj.get("object_kind") != "Pod":
            continue
        ns = obj.get("namespace") or "default"
        pid = _obj_id("Pod", obj.get("object_name"), ns)
        spec = obj.get("body", {}).get("spec", {}) or {}
        sa = spec.get("serviceAccountName")
        if sa:
            builder.add_edge(pid, "depends_on", _obj_id("ServiceAccount", sa, ns))

        # Volumes
        for vol in spec.get("volumes", []) or []:
            if "configMap" in vol:
                cm = vol["configMap"].get("name")
                if cm:
                    builder.add_edge(pid, "depends_on", _obj_id("ConfigMap", cm, ns))
            if "secret" in vol:
                sec = vol["secret"].get("secretName")
                if sec:
                    builder.add_edge(pid, "depends_on", _obj_id("Secret", sec, ns))
            if "projected" in vol:
                for src in vol["projected"].get("sources", []) or []:
                    if "configMap" in src and src["configMap"].get("name"):
                        builder.add_edge(pid, "depends_on", _obj_id("ConfigMap", src["configMap"]["name"], ns))
                    if "secret" in src and src["secret"].get("name"):
                        builder.add_edge(pid, "depends_on", _obj_id("Secret", src["secret"]["name"], ns))
            if "persistentVolumeClaim" in vol:
                pvc = vol["persistentVolumeClaim"].get("claimName")
                if pvc:
                    builder.add_edge(pid, "depends_on", _obj_id("PersistentVolumeClaim", pvc, ns))

        def handle_env(container: dict[str, Any]) -> None:
            for env in container.get("env", []) or []:
                val_from = env.get("valueFrom") or {}
                if "configMapKeyRef" in val_from and val_from["configMapKeyRef"].get("name"):
                    builder.add_edge(pid, "depends_on", _obj_id("ConfigMap", val_from["configMapKeyRef"]["name"], ns))
                if "secretKeyRef" in val_from and val_from["secretKeyRef"].get("name"):
                    builder.add_edge(pid, "depends_on", _obj_id("Secret", val_from["secretKeyRef"]["name"], ns))
                val = env.get("value")
                if isinstance(val, str):
                    for svc in telemetry_services:
                        if svc in val:
                            builder.add_edge(pid, "depends_on", _obj_id("Service", svc, ns))
            for env_from in container.get("envFrom", []) or []:
                if env_from.get("configMapRef", {}).get("name"):
                    builder.add_edge(pid, "depends_on", _obj_id("ConfigMap", env_from["configMapRef"]["name"], ns))
                if env_from.get("secretRef", {}).get("name"):
                    builder.add_edge(pid, "depends_on", _obj_id("Secret", env_from["secretRef"]["name"], ns))

        for container in spec.get("containers", []) or []:
            handle_env(container)
        for container in spec.get("initContainers", []) or []:
            handle_env(container)

    # High-level nodes (services + infrastructure from arch)
    hl_services = [svc["name"] for svc in arch.get("components", {}).get("services", [])]
    hl_infra = [item["name"] for item in arch.get("components", {}).get("infrastructure", [])]
    hl_all = list(dict.fromkeys(hl_services + hl_infra))
    for name in hl_all:
        builder.add_node({"id": name, "kind": "App", "name": name})

    # Map high-level names to actual Service names in Kubernetes
    alias_map = {
        "ad-service": "ad",
        "cart-service": "cart",
        "checkout-service": "checkout",
        "currency-service": "currency",
        "product-catalog-service": "product-catalog",
        "recommendation-service": "recommendation",
        "shipping-service": "shipping",
        "product-reviews-service": "product-reviews",
        "email-service": "email",
        "payment-service": "payment",
        "quote-service": "quote",
        "valkey": "valkey-cart",
        "frontend-proxy": "frontend-proxy",
        "load-generator": "load-generator",
        "frontend": "frontend",
        "kafka": "kafka",
        "postgresql": "postgresql",
        "accounting-service": "accounting",
        "fraud-detection-service": "fraud-detection",
        "opentelemetry-collector": "otel-collector",
    }
    default_ns = "otel-demo"

    def resolve_service(name: str) -> Optional[str]:
        mapped = alias_map.get(name, name)
        if default_ns in services and mapped in services[default_ns]:
            return services[default_ns][mapped]
        return None

    # Alias edges from high-level names to actual services
    for hl_name in hl_all:
        actual = resolve_service(hl_name)
        if actual and actual != hl_name:
            builder.add_edge(hl_name, "is_alias", actual)

    # High-level dependencies (calls)
    for dep in arch.get("dependencies", []):
        src = dep["source"]
        tgt = dep["target"]
        meta = {k: v for k, v in dep.items() if k not in ["source", "target"]}

        builder.add_node({"id": src, "kind": "App", "name": src})
        builder.add_node({"id": tgt, "kind": "App", "name": tgt})

        actual_target = resolve_service(tgt) or tgt
        builder.add_edge(src, "calls", actual_target, meta if meta else None)

    return {"nodes": builder.nodes, "edges": builder.edges}


def build_topology_standalone(arch_file: str, k8s_objects_file: str, output_file: str) -> dict[str, Any]:
    """Build topology without MCP server (for direct Python testing).

    Args:
        arch_file: Path to application architecture JSON file
        k8s_objects_file: Path to Kubernetes objects TSV file
        output_file: Path to write the topology JSON output

    Returns:
        Dictionary with 'nodes' and 'edges' lists

    Raises:
        FileNotFoundError: If input files don't exist
        ValueError: If files are invalid

    Example:
        >>> from sre_tools.offline_incident_analysis.tools import build_topology_standalone
        >>> topology = build_topology_standalone(
        ...     arch_file="app/arch.json",
        ...     k8s_objects_file="k8s_objects_otel-demo_chaos-mesh.tsv",
        ...     output_file="topology.json"
        ... )
        >>> print(f"Built topology with {len(topology['nodes'])} nodes")
    """
    arch_path = Path(arch_file)
    k8s_path = Path(k8s_objects_file)
    output_path = Path(output_file)

    if not arch_path.exists():
        raise FileNotFoundError(f"Architecture file not found: {arch_file}")
    if not k8s_path.exists():
        raise FileNotFoundError(f"K8s objects file not found: {k8s_objects_file}")

    topology = _do_build_topology(arch_path, k8s_path)

    # Write to output file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(topology, indent=2))

    return topology


# =============================================================================
# Command-Line Interface
# =============================================================================
