"""
Context aggregation across multiple data sources.
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


def _find_scenario_files(scenario_dir: Path) -> dict[str, Optional[Path]]:
    """Find common scenario files in a directory.

    Uses flexible wildcard patterns to match various file naming conventions:
    - Events: *events*.tsv (matches k8s_events_raw.tsv, events.tsv, etc.)
    - Objects: *objects*.tsv (matches k8s_objects_raw.tsv, objects.tsv, etc.)
    - Traces: *traces*.tsv (matches otel_traces_raw.tsv, traces.tsv, etc.)
    - Logs: *logs*.tsv (matches otel_logs_raw.tsv, logs.tsv, etc.)
    - Topology: *topology*.json (matches operational_topology.json, topology.json, etc.)
    """
    files: dict[str, Optional[Path]] = {
        "events_file": None,
        "objects_file": None,
        "traces_file": None,
        "logs_file": None,
        "alerts_dir": None,
        "metrics_dir": None,
        "topology_file": None,
    }

    # Find events file (*events*.tsv)
    for f in scenario_dir.glob("*events*.tsv"):
        files["events_file"] = f
        break

    # Find objects file (*objects*.tsv)
    for f in scenario_dir.glob("*objects*.tsv"):
        files["objects_file"] = f
        break

    # Find traces file (*traces*.tsv)
    for f in scenario_dir.glob("*traces*.tsv"):
        files["traces_file"] = f
        break

    # Find logs file (*logs*.tsv)
    for f in scenario_dir.glob("*logs*.tsv"):
        files["logs_file"] = f
        break

    # Find alerts directory
    alerts_dir = scenario_dir / "alerts"
    if alerts_dir.is_dir():
        files["alerts_dir"] = alerts_dir

    # Find metrics directory
    metrics_dir = scenario_dir / "metrics"
    if metrics_dir.is_dir():
        files["metrics_dir"] = metrics_dir

    # Find topology file (*topology*.json)
    for f in scenario_dir.glob("*topology*.json"):
        files["topology_file"] = f
        break

    return files


async def _get_context_contract(args: dict[str, Any]) -> list[TextContent]:
    """Aggregate full operational context for a K8s entity.

    Calls multiple analysis tools internally to build a comprehensive context:
    1. Dependencies (via topology_analysis)
    2. Events (via event_analysis)
    3. Alerts (via alert_analysis)
    4. Trace errors (via get_trace_error_tree)
    5. Metric anomalies (via get_metric_anomalies)
    6. Log patterns (via log_analysis with pattern mining)
    7. K8s object spec (via get_k8_spec - latest spec for the entity)
    8. Spec changes (via k8s_spec_change_analysis)

    Pagination:
    - Page 1: Main entity context
    - Page 2+: Dependency context (deps_per_page dependencies per page)
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    k8_object = args.get("k8_object", "")
    snapshot_dir_str = args.get("snapshot_dir", "")
    topology_file = args.get("topology_file")
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    page = args.get("page", 1)
    deps_per_page = args.get("deps_per_page", 3)

    if not k8_object:
        return [TextContent(type="text", text="Error: 'k8_object' is required")]
    if not snapshot_dir_str:
        return [TextContent(type="text", text="Error: 'snapshot_dir' is required")]

    snapshot_dir = Path(snapshot_dir_str)
    if not snapshot_dir.is_dir():
        return [TextContent(type="text", text=f"Error: snapshot_dir not found: {snapshot_dir}")]

    # Find snapshot files
    files = _find_scenario_files(snapshot_dir)

    # Override topology file if provided
    if topology_file:
        files["topology_file"] = Path(topology_file)

    # Parse entity identifier using flexible format support
    # Accepts:
    # - namespace/kind/name (PREFERRED - unambiguous)
    # - kind/name (ambiguous - may match multiple namespaces)
    # - name (most ambiguous)
    parsed_id = _parse_k8_object_identifier(k8_object)

    entity_kind = parsed_id.get("kind") or "Unknown"
    entity_namespace = parsed_id.get("namespace")
    entity_short_name = parsed_id.get("name", "")

    # Name used for searching/filtering across traces/metrics/events (usually service/deploy name).
    entity_search_name = entity_short_name
    # Display name (keep namespace if provided).
    entity_display_name = f"{entity_namespace}/{entity_short_name}" if entity_namespace else entity_short_name

    # Include format warning in result if identifier is ambiguous
    id_format_warning = parsed_id.get("warning")

    result: dict[str, Any] = {
        "entity": k8_object,
        "identifier_format": parsed_id.get("format"),
        "kind": entity_kind,
        "namespace": entity_namespace,
        "name": entity_display_name,
        "page": page,
        "snapshot_dir": str(snapshot_dir),
        "time_window": {"start": start_time, "end": end_time},
        "files_found": {k: str(v) if v else None for k, v in files.items()},
    }

    # Add warning for ambiguous identifiers
    if id_format_warning:
        result["identifier_warning"] = id_format_warning

    # ========== GET DEPENDENCIES (Always needed for pagination info) ==========
    # Strategy: Direct deps (hop 0) + One transitive hop (hop 1)
    # Only follow 'calls' and 'depends_on' edges, NOT 'contains'
    # Note: depends_on relationships are often at the Pod level, so we also check
    # the backing_infrastructure pods for their dependencies.

    def _extract_functional_deps(topo_data: dict) -> set:
        """Extract functional dependencies (calls, depends_on) from topology data."""
        deps = set()

        # Add callees (services this entity calls)
        if "callees" in topo_data:
            deps.update(topo_data["callees"])

        # Add from relationships_by_type (outgoing calls and depends_on)
        if "relationships_by_type" in topo_data:
            for rel_type, targets in topo_data["relationships_by_type"].items():
                if "--calls-->" in rel_type or "--depends_on-->" in rel_type:
                    deps.update(targets)

        return deps

    def _extract_pods_from_backing_infra(topo_data: dict) -> list[str]:
        """Extract Pod IDs from backing_infrastructure strings."""
        pods = []
        for chain in topo_data.get("backing_infrastructure", []):
            # Parse strings like "ReplicaSet/cart-xxx --contains--> Pod/cart-xxx-yyy"
            if "--contains--> Pod/" in chain:
                pod_part = chain.split("--contains--> ")[-1]
                if pod_part.startswith("Pod/"):
                    pods.append(pod_part)
        return pods

    dependencies: list[str] = []
    direct_deps: set[str] = set()
    transitive_deps: set[str] = set()

    if files["topology_file"] and files["topology_file"].exists():
        try:
            # Get direct dependencies (hop 0)
            topo_result = await _topology_analysis(
                {"topology_file": str(files["topology_file"]), "entity": entity_search_name}
            )
            topo_text = topo_result[0].text
            topo_data = json.loads(topo_text)

            # Get deps from the entity itself (calls, depends_on)
            direct_deps = _extract_functional_deps(topo_data)

            # Also get deps from the backing infrastructure pods
            # (depends_on relationships are often at Pod level)
            backing_pods = _extract_pods_from_backing_infra(topo_data)
            for pod_id in backing_pods[:3]:  # Limit to first 3 pods to avoid explosion
                try:
                    pod_topo_result = await _topology_analysis(
                        {"topology_file": str(files["topology_file"]), "entity": pod_id}
                    )
                    pod_topo_data = json.loads(pod_topo_result[0].text)
                    pod_deps = _extract_functional_deps(pod_topo_data)
                    direct_deps.update(pod_deps)
                except Exception:
                    pass

            # Get transitive dependencies (hop 1) - deps of our direct deps
            for dep in list(direct_deps):
                try:
                    dep_topo_result = await _topology_analysis(
                        {"topology_file": str(files["topology_file"]), "entity": dep}
                    )
                    dep_topo_data = json.loads(dep_topo_result[0].text)

                    # Get this dep's dependencies (including from its pods)
                    dep_deps = _extract_functional_deps(dep_topo_data)

                    # Also check backing pods of this dependency
                    dep_pods = _extract_pods_from_backing_infra(dep_topo_data)
                    for pod_id in dep_pods[:2]:  # Limit to 2 pods per dep
                        try:
                            pod_topo_result = await _topology_analysis(
                                {"topology_file": str(files["topology_file"]), "entity": pod_id}
                            )
                            pod_topo_data = json.loads(pod_topo_result[0].text)
                            dep_deps.update(_extract_functional_deps(pod_topo_data))
                        except Exception:
                            pass

                    # Add to transitive (excluding things we already have)
                    for dd in dep_deps:
                        if (
                            dd not in direct_deps
                            and dd != entity_search_name
                            and dd != k8_object
                            and dd != f"{entity_kind}/{entity_display_name}"
                        ):
                            transitive_deps.add(dd)
                except Exception:
                    # If we can't analyze a dependency, skip it
                    pass

            # Combine: direct deps first, then transitive
            all_deps = direct_deps | transitive_deps
            dependencies = sorted(list(all_deps))

            if page == 1 or page == 0:
                result["topology"] = topo_data
                result["dependency_breakdown"] = {
                    "direct": sorted(list(direct_deps)),
                    "transitive": sorted(list(transitive_deps)),
                }
        except Exception as e:
            result["topology_error"] = str(e)

    # Calculate pagination info
    total_dep_pages = (len(dependencies) + deps_per_page - 1) // deps_per_page if dependencies else 0
    total_pages = 1 + total_dep_pages  # Page 1 = main entity, Page 2+ = dependencies

    result["pagination"] = {
        "current_page": page,
        "total_pages": total_pages,
        "total_dependencies": len(dependencies),
        "deps_per_page": deps_per_page,
        "all_pages": page == 0,
    }

    # ========== PAGE 0 or PAGE 1: MAIN ENTITY CONTEXT ==========
    if page == 0 or page == 1:
        result["context_type"] = "main_entity"

        # 1. Events for this entity
        if files["events_file"]:
            try:
                event_args = {
                    "events_file": str(files["events_file"]),
                    "filters": {},
                }
                if start_time:
                    event_args["start_time"] = start_time
                if end_time:
                    event_args["end_time"] = end_time

                # Filter by entity name - try multiple patterns to handle naming variations
                # e.g., "product-catalog-service" should match "product-catalog"
                base_name = entity_search_name.lower()
                name_variants = [base_name]
                for suffix in ["-service", "_service", "-svc", "_svc"]:
                    if base_name.endswith(suffix):
                        name_variants.append(base_name[: -len(suffix)])

                events_data = []
                for variant in name_variants:
                    event_result = await _event_analysis(
                        {
                            **event_args,
                            "filters": (
                                {"deployment": variant}
                                if entity_kind in ["Deployment", "Service", "App"]
                                else {"object_name": variant}
                            ),
                        }
                    )
                    response_text = event_result[0].text
                    # Handle both JSON and error text responses
                    try:
                        parsed = json.loads(response_text)
                        # Extract data from the response object
                        if isinstance(parsed, dict) and "data" in parsed:
                            events_data = parsed["data"]
                        elif isinstance(parsed, list):
                            events_data = parsed
                        else:
                            events_data = []
                        if events_data:
                            break
                    except json.JSONDecodeError:
                        # Response was an error message, not JSON
                        continue

                result["events"] = {
                    "count": len(events_data),
                    "items": {
                        "data": events_data,
                        "limit": "all",
                        "offset": 0,
                        "returned_count": len(events_data),
                        "total_count": len(events_data),
                    },
                    "truncated": False,
                }
            except Exception as e:
                result["events_error"] = str(e)

        # 2. Alerts
        if files["alerts_dir"]:
            try:
                alert_args = {"base_dir": str(files["alerts_dir"]), "limit": 20}
                if start_time:
                    alert_args["start_time"] = start_time
                if end_time:
                    alert_args["end_time"] = end_time

                alert_result = await _alert_analysis(alert_args)
                alerts_data = json.loads(alert_result[0].text)

                # Filter alerts related to this entity
                related_alerts = [a for a in alerts_data if entity_name.lower() in str(a).lower()]

                result["alerts"] = {
                    "total_alerts": len(alerts_data),
                    "related_to_entity": len(related_alerts),
                    "items": related_alerts[:10],
                    "truncated": len(related_alerts) > 10,
                }
            except Exception as e:
                result["alerts_error"] = str(e)

        # 3. Trace error tree
        if files["traces_file"]:
            try:
                # Try multiple name patterns to handle naming variations
                base_name = entity_search_name.lower()
                name_variants = [base_name]
                for suffix in ["-service", "_service", "-svc", "_svc"]:
                    if base_name.endswith(suffix):
                        name_variants.append(base_name[: -len(suffix)])

                trace_data = None
                for variant in name_variants:
                    trace_args = {"trace_file": str(files["traces_file"]), "service_name": variant}
                    if start_time:
                        trace_args["pivot_time"] = start_time

                    trace_result = await _get_trace_error_tree(trace_args)
                    response_text = trace_result[0].text

                    # Handle both JSON and error text responses
                    try:
                        parsed = json.loads(response_text)
                        # Check if we got actual trace data (not just an error object)
                        if isinstance(parsed, dict) and ("critical_paths" in parsed or "all_paths" in parsed):
                            trace_data = parsed
                            break
                    except json.JSONDecodeError:
                        # Response was an error message, try next variant
                        continue

                if trace_data:
                    result["trace_errors"] = trace_data
                else:
                    result["trace_errors"] = {
                        "message": "No trace data found for entity",
                        "variants_tried": name_variants,
                    }
            except Exception as e:
                result["trace_errors_error"] = str(e)

        # 4. Metric anomalies
        if files["metrics_dir"]:
            try:
                # Choose a metrics target that actually exists in the snapshot.
                #
                # Metrics snapshots typically have pod_*.tsv and service_*.tsv, not deployment_*.tsv.
                # For Deployment/App entities, try service/<name> first, then a backing pod.
                base_name = entity_search_name.lower()
                name_variants = [base_name]
                # Remove common suffixes to handle naming mismatches
                for suffix in ["-service", "_service", "-svc", "_svc"]:
                    if base_name.endswith(suffix):
                        name_variants.append(base_name[: -len(suffix)])

                async def _try_metric_target(k8_obj_name: str) -> dict[str, Any] | None:
                    anomaly_args = {
                        "base_dir": str(files["metrics_dir"]),
                        "k8_object_name": k8_obj_name,
                        "raw_content": False,
                    }
                    if start_time:
                        anomaly_args["start_time"] = start_time
                    if end_time:
                        anomaly_args["end_time"] = end_time

                    anomaly_result = await _get_metric_anomalies(anomaly_args)
                    anomaly_data = json.loads(anomaly_result[0].text)
                    # Only accept if it returned at least one metric entry.
                    if isinstance(anomaly_data, dict) and anomaly_data.get("metrics"):
                        return anomaly_data
                    return None

                metric_anomalies = None
                kind_lower = entity_kind.lower()
                # Direct pod/service entity -> try itself (without namespace in name).
                if kind_lower in ("pod", "service"):
                    metric_anomalies = await _try_metric_target(f"{entity_kind}/{entity_short_name}")
                else:
                    # Deployment/App/etc -> try service first.
                    for variant in name_variants:
                        metric_anomalies = await _try_metric_target(f"Service/{variant}")
                        if metric_anomalies:
                            break

                    # Fallback: pick a pod metric file matching the deployment name.
                    if not metric_anomalies:
                        for variant in name_variants:
                            pod_files = sorted(files["metrics_dir"].glob(f"pod_{variant}-*.tsv"))
                            if not pod_files:
                                continue
                            pod_stem = pod_files[0].name.replace(".tsv", "")
                            # pod_<podname>[_raw].tsv -> podname includes hashes.
                            pod_name = pod_stem.split("_", 1)[1]
                            metric_anomalies = await _try_metric_target(f"pod/{pod_name}")
                            if metric_anomalies:
                                break

                if metric_anomalies:
                    result["metric_anomalies"] = metric_anomalies
            except Exception as e:
                result["metric_anomalies_error"] = str(e)

        # 5. Log patterns (via log_analysis with pattern mining)
        if files["logs_file"]:
            try:
                log_args = {
                    "logs_file": str(files["logs_file"]),
                    "k8_object": k8_object,
                    "pattern_analysis": True,
                    "max_patterns": 15,  # Top 15 patterns
                    "similarity_threshold": 0.5,
                }
                if start_time:
                    log_args["start_time"] = start_time
                if end_time:
                    log_args["end_time"] = end_time

                log_result = await _log_analysis(log_args)
                log_data = json.loads(log_result[0].text)

                # Include pattern summary in context
                if log_data.get("total_logs", 0) > 0:
                    result["log_patterns"] = {
                        "total_logs": log_data.get("total_logs", 0),
                        "pattern_count": log_data.get("pattern_count", 0),
                        "patterns": log_data.get("patterns", []),
                    }
                else:
                    result["log_patterns"] = {"total_logs": 0, "message": "No logs found for entity in time window"}
            except Exception as e:
                result["log_patterns_error"] = str(e)

        # 6. Latest K8s object spec (via get_k8_spec)
        if files["objects_file"]:
            try:
                k8_spec_args = {
                    "k8s_objects_file": str(files["objects_file"]),
                    "k8_object_name": k8_object,
                    "include_metadata": True,
                }
                k8_spec_result = await _get_k8_spec(k8_spec_args)
                k8_spec_data = json.loads(k8_spec_result[0].text)

                if k8_spec_data.get("found"):
                    # Truncate large specs for readability
                    spec_str = json.dumps(k8_spec_data.get("spec", {}))
                    if len(spec_str) > 2000:
                        result["k8s_spec"] = {
                            "entity_id": k8_spec_data.get("entity_id"),
                            "kind": k8_spec_data.get("kind"),
                            "namespace": k8_spec_data.get("namespace"),
                            "name": k8_spec_data.get("name"),
                            "timestamp": k8_spec_data.get("timestamp"),
                            "observation_count": k8_spec_data.get("observation_count"),
                            "spec_truncated": True,
                            "spec_preview": spec_str[:2000] + "...",
                        }
                    else:
                        result["k8s_spec"] = {
                            "entity_id": k8_spec_data.get("entity_id"),
                            "kind": k8_spec_data.get("kind"),
                            "namespace": k8_spec_data.get("namespace"),
                            "name": k8_spec_data.get("name"),
                            "timestamp": k8_spec_data.get("timestamp"),
                            "observation_count": k8_spec_data.get("observation_count"),
                            "spec": k8_spec_data.get("spec"),
                        }
                else:
                    result["k8s_spec_error"] = k8_spec_data.get("error", "Resource not found")
            except Exception as e:
                result["k8s_spec_error"] = str(e)

        # 7. Spec changes
        if files["objects_file"]:
            try:
                spec_args = {"k8s_objects_file": str(files["objects_file"]), "k8_object_name": k8_object}
                if start_time:
                    spec_args["start_time"] = start_time
                if end_time:
                    spec_args["end_time"] = end_time

                spec_result = await _k8s_spec_change_analysis(spec_args)
                spec_data = json.loads(spec_result[0].text)
                result["spec_changes"] = spec_data
            except Exception as e:
                result["spec_changes_error"] = str(e)

        # 8. Dependencies list (for reference)
        result["dependencies"] = dependencies

        # If page=0, also include ALL dependency context
        if page == 0 and dependencies:
            result["context_type"] = "all"
            result["dependency_context"] = {}

            for dep in dependencies:
                dep_context: dict[str, Any] = {"entity": dep}

                # Events for dependency
                if files["events_file"]:
                    try:
                        event_args = {
                            "events_file": str(files["events_file"]),
                            "filters": (
                                {"deployment": dep}
                                if not dep.startswith("Pod/")
                                else {"object_name": dep.split("/")[-1]}
                            ),
                            "limit": 10,
                        }
                        if start_time:
                            event_args["start_time"] = start_time
                        if end_time:
                            event_args["end_time"] = end_time

                        event_result = await _event_analysis(event_args)
                        events_data = json.loads(event_result[0].text)
                        dep_context["events"] = {"count": len(events_data), "items": events_data[:5]}
                    except Exception as e:
                        dep_context["events_error"] = str(e)

                # Spec changes for dependency
                if files["objects_file"]:
                    try:
                        spec_args = {"k8s_objects_file": str(files["objects_file"]), "k8_object_name": dep}
                        if start_time:
                            spec_args["start_time"] = start_time
                        if end_time:
                            spec_args["end_time"] = end_time

                        spec_result = await _k8s_spec_change_analysis(spec_args)
                        spec_data = json.loads(spec_result[0].text)
                        dep_context["spec_changes"] = spec_data
                    except Exception as e:
                        dep_context["spec_changes_error"] = str(e)

                result["dependency_context"][dep] = dep_context

    # ========== PAGE 2+: DEPENDENCY CONTEXT (paginated) ==========
    elif page >= 2:
        result["context_type"] = "dependencies"

        # Calculate which dependencies to show on this page
        start_idx = (page - 2) * deps_per_page
        end_idx = start_idx + deps_per_page
        page_deps = dependencies[start_idx:end_idx]

        if not page_deps:
            result["message"] = f"No dependencies on page {page}. Total pages: {total_pages}"
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        result["dependencies_on_page"] = page_deps
        result["dependency_context"] = {}

        for dep in page_deps:
            dep_context: dict[str, Any] = {"entity": dep}

            # Events for dependency
            if files["events_file"]:
                try:
                    event_args = {
                        "events_file": str(files["events_file"]),
                        "filters": (
                            {"deployment": dep} if not dep.startswith("Pod/") else {"object_name": dep.split("/")[-1]}
                        ),
                        "limit": 10,
                    }
                    if start_time:
                        event_args["start_time"] = start_time
                    if end_time:
                        event_args["end_time"] = end_time

                    event_result = await _event_analysis(event_args)
                    events_data = json.loads(event_result[0].text)
                    dep_context["events"] = {"count": len(events_data), "items": events_data[:5]}
                except Exception as e:
                    dep_context["events_error"] = str(e)

            # Spec changes for dependency
            if files["objects_file"]:
                try:
                    spec_args = {"k8s_objects_file": str(files["objects_file"]), "k8_object_name": dep}
                    if start_time:
                        spec_args["start_time"] = start_time
                    if end_time:
                        spec_args["end_time"] = end_time

                    spec_result = await _k8s_spec_change_analysis(spec_args)
                    spec_data = json.loads(spec_result[0].text)
                    dep_context["spec_changes"] = spec_data
                except Exception as e:
                    dep_context["spec_changes_error"] = str(e)

            result["dependency_context"][dep] = dep_context

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# =============================================================================
# Standalone execution support (for testing without MCP)
# =============================================================================
