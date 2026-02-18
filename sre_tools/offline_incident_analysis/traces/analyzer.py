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

from ..shared import _format_latency, _format_rate, _parse_duration, _parse_time

from .stats import _compute_delta, _compute_percentiles


def _extract_service_path_from_trace(spans: List[Dict[str, Any]]) -> List[str]:
    """
    Extract the collapsed service path from a trace's spans.
    Uses parent_span_id to reconstruct the call hierarchy, then collapses consecutive same services.
    Returns list of unique services in order (e.g., ['frontend', 'checkout', 'payment']).
    """
    if not spans:
        return []

    # Build span lookup and find root
    span_map = {s["span_id"]: s for s in spans if s.get("span_id")}
    children_map: Dict[str, List[str]] = {}
    roots = []

    for s in spans:
        sid = s.get("span_id")
        pid = s.get("parent_span_id")
        if pid and pid in span_map:
            children_map.setdefault(pid, []).append(sid)
        elif sid:
            roots.append(sid)

    if not roots:
        return []

    # DFS to find the longest path (leaf path)
    def get_leaf_path(span_id: str) -> List[str]:
        span = span_map.get(span_id)
        if not span:
            return []

        svc = span.get("service_name", "unknown")
        children = children_map.get(span_id, [])

        if not children:
            return [svc]

        # Get the longest child path
        longest = []
        for child_id in children:
            child_path = get_leaf_path(child_id)
            if len(child_path) > len(longest):
                longest = child_path

        return [svc] + longest

    # Get full path from first root
    full_path = get_leaf_path(roots[0])

    # Collapse consecutive same services
    collapsed = []
    prev = None
    for svc in full_path:
        if svc != prev:
            collapsed.append(svc)
            prev = svc

    return collapsed


def _group_traces_by_path(
    spans_by_trace: Dict[str, List[Dict[str, Any]]], target_service: str = None
) -> Dict[str, Dict[str, Any]]:
    """
    Group traces by their unique service path.
    Returns: {path_key: {"services": [...], "trace_ids": set(), "spans_by_service": {...}}}
    """
    path_groups: Dict[str, Dict[str, Any]] = {}

    for trace_id, spans in spans_by_trace.items():
        # Extract service path for this trace
        service_path = _extract_service_path_from_trace(spans)

        if not service_path:
            continue

        # Skip if target_service specified and not in path
        if target_service and target_service not in service_path:
            continue

        path_key = " → ".join(service_path)

        if path_key not in path_groups:
            path_groups[path_key] = {
                "services": service_path,
                "trace_ids": set(),
                "spans": [],  # All spans belonging to traces on this path
            }

        path_groups[path_key]["trace_ids"].add(trace_id)
        path_groups[path_key]["spans"].extend(spans)

    return path_groups


def _compute_path_stats(
    path_group: Dict[str, Any],
    pre_start: datetime,
    pre_end: datetime,
    post_start: datetime,
    post_end: datetime,
    window_duration_sec: float,
) -> Dict[str, Any]:
    """
    Compute pre/post stats for each service in a path, using only spans from this path's traces.
    """
    spans = path_group["spans"]
    services = path_group["services"]

    # Group spans by service
    spans_by_service: Dict[str, List[Dict[str, Any]]] = {}
    for span in spans:
        svc = span.get("service_name", "unknown")
        spans_by_service.setdefault(svc, []).append(span)

    # Compute stats per service
    service_stats = {}
    error_messages = set()

    for svc in services:
        svc_spans = spans_by_service.get(svc, [])

        pre_stats = {"count": 0, "errors": 0, "latencies": []}
        post_stats = {"count": 0, "errors": 0, "latencies": []}

        for span in svc_spans:
            ts_str = span.get("timestamp")
            if not ts_str:
                continue

            try:
                ts = _parse_time(ts_str)
                # Normalize timezone
                if ts.tzinfo is None and pre_start.tzinfo is not None:
                    ts = ts.replace(tzinfo=pre_start.tzinfo)
                elif ts.tzinfo is not None and pre_start.tzinfo is None:
                    ts = ts.replace(tzinfo=None)

                # Determine window
                if pre_start <= ts < pre_end:
                    window = pre_stats
                elif post_start <= ts < post_end:
                    window = post_stats
                else:
                    continue

                window["count"] += 1

                if span.get("status_code") == "Error":
                    window["errors"] += 1
                    msg = span.get("status_message")
                    if msg:
                        error_messages.add(msg[:200])

                try:
                    dur = float(span.get("duration_ms", 0))
                    window["latencies"].append(dur)
                except (ValueError, TypeError):
                    pass
            except:
                continue

        service_stats[svc] = {"pre": pre_stats, "post": post_stats}

    # Compute path-level stats (sum across all services)
    path_pre = {"count": 0, "errors": 0, "latencies": []}
    path_post = {"count": 0, "errors": 0, "latencies": []}

    for svc, stats in service_stats.items():
        path_pre["count"] += stats["pre"]["count"]
        path_pre["errors"] += stats["pre"]["errors"]
        path_pre["latencies"].extend(stats["pre"]["latencies"])
        path_post["count"] += stats["post"]["count"]
        path_post["errors"] += stats["post"]["errors"]
        path_post["latencies"].extend(stats["post"]["latencies"])

    return {
        "services": services,
        "trace_count": len(path_group["trace_ids"]),
        "pre": path_pre,
        "post": path_post,
        "service_stats": service_stats,
        "error_messages": error_messages,
        "window_duration_sec": window_duration_sec,
    }


def _classify_severity(
    pre_stats: Dict[str, Any], post_stats: Dict[str, Any], error_threshold: float, latency_threshold: float
) -> tuple:
    """
    Classify severity and return (severity, is_critical).
    Returns: ("CRITICAL", True), ("WARNING", True), ("NEW", True), ("DISAPPEARED", True), or (None, False)
    """
    if not pre_stats.get("count") and post_stats.get("count"):
        return ("NEW", True)
    if pre_stats.get("count") and not post_stats.get("count"):
        return ("DISAPPEARED", True)
    if not pre_stats.get("count") and not post_stats.get("count"):
        return (None, False)

    # Compute metrics
    pre_err = (pre_stats["errors"] / pre_stats["count"] * 100) if pre_stats["count"] > 0 else 0
    post_err = (post_stats["errors"] / post_stats["count"] * 100) if post_stats["count"] > 0 else 0

    pre_lat = _compute_percentiles(pre_stats["latencies"])["p99"]
    post_lat = _compute_percentiles(post_stats["latencies"])["p99"]

    err_change = abs(_compute_delta(pre_err, post_err)) if pre_err > 0 or post_err > 0 else 0
    lat_change = abs(_compute_delta(pre_lat, post_lat)) if pre_lat > 0 or post_lat > 0 else 0

    # Check if exceeds thresholds
    err_exceeds = err_change > error_threshold or (pre_err == 0 and post_err > error_threshold)
    lat_exceeds = lat_change > latency_threshold

    if not err_exceeds and not lat_exceeds:
        return (None, False)

    # Classify severity
    if err_change > 50 or post_err > 50 or lat_change > 100:
        return ("CRITICAL", True)
    else:
        return ("WARNING", True)


def _normalize_trace_columns(span: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize trace column names to snake_case for consistent access.

    Handles various column naming conventions:
    - TraceId -> trace_id
    - SpanId -> span_id
    - ParentSpanId -> parent_span_id
    - ServiceName -> service_name
    - StatusCode -> status_code
    - Duration -> duration
    etc.
    """
    # Common column mappings (CamelCase -> snake_case)
    column_map = {
        "TraceId": "trace_id",
        "SpanId": "span_id",
        "ParentSpanId": "parent_span_id",
        "TraceState": "trace_state",
        "SpanName": "span_name",
        "SpanKind": "span_kind",
        "ServiceName": "service_name",
        "ResourceAttributes": "resource_attributes",
        "ScopeName": "scope_name",
        "ScopeVersion": "scope_version",
        "SpanAttributes": "span_attributes",
        "Duration": "duration",
        "StatusCode": "status_code",
        "StatusMessage": "status_message",
        "Timestamp": "timestamp",
    }

    normalized = {}
    for key, value in span.items():
        # Use mapping if available, otherwise convert CamelCase to snake_case
        if key in column_map:
            normalized[column_map[key]] = value
        else:
            # Keep original key as fallback (handles already snake_case keys)
            normalized[key] = value
            # Also add snake_case version for CamelCase keys
            snake_key = "".join(["_" + c.lower() if c.isupper() else c for c in key]).lstrip("_")
            if snake_key != key:
                normalized[snake_key] = value

    return normalized


async def _get_trace_error_tree(args: dict[str, Any]) -> list[TextContent]:
    """
    Trace-based analysis: groups by trace_id to correctly stitch paths and compute per-service stats.
    """
    trace_file = args.get("trace_file", "")
    service_name = args.get("service_name")
    span_kind_filter = args.get("span_kind")
    pivot_time_str = args.get("pivot_time")
    delta_time_str = args.get("delta_time", "5m")
    error_threshold = args.get("error_threshold_pct", 10)
    latency_threshold = args.get("latency_threshold_pct", 10)

    try:
        traces = read_tsv_file(trace_file)
    except FileNotFoundError:
        return [TextContent(type="text", text=f"Trace file not found: {trace_file}")]

    if not traces:
        return [TextContent(type="text", text="No traces found in file")]

    # Normalize column names to snake_case for consistent access
    traces = [_normalize_trace_columns(span) for span in traces]

    delta = _parse_duration(delta_time_str)
    pivot_time = _parse_time(pivot_time_str) if pivot_time_str else None

    # Step 1: Group spans by trace_id
    spans_by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for span in traces:
        tid = span.get("trace_id")
        if tid:
            spans_by_trace.setdefault(tid, []).append(span)

    # Step 2: Determine time windows
    if pivot_time:
        pre_start = pivot_time - delta
        pre_end = pivot_time
        post_start = pivot_time
        post_end = pivot_time + delta
    else:
        # Find time bounds from all spans
        timestamps = []
        for spans in spans_by_trace.values():
            for s in spans:
                try:
                    ts = _parse_time(s.get("timestamp"))
                    if ts:
                        timestamps.append(ts)
                except:
                    pass
        if timestamps:
            pre_start = pre_end = None
            post_start = min(timestamps)
            post_end = max(timestamps)
        else:
            return [TextContent(type="text", text="No valid timestamps in traces")]

    window_duration_sec = delta.total_seconds() if pivot_time else (post_end - post_start).total_seconds()
    if window_duration_sec <= 0:
        window_duration_sec = 1

    # Step 3: Group traces by their unique service path
    path_groups = _group_traces_by_path(spans_by_trace, service_name)

    if not path_groups:
        return [
            TextContent(
                type="text",
                text=(
                    f"No traces found containing service: {service_name}"
                    if service_name
                    else "No valid trace paths found"
                ),
            )
        ]

    # Step 4: Compute stats for each path
    path_stats_list = []
    for path_key, path_group in path_groups.items():
        if pivot_time:
            stats = _compute_path_stats(path_group, pre_start, pre_end, post_start, post_end, window_duration_sec)
        else:
            # Single window mode - use post_start/end as the only window, pre is empty
            stats = _compute_path_stats(
                path_group, post_start, post_start, post_start, post_end, window_duration_sec  # Empty pre window
            )
        stats["path_key"] = path_key
        path_stats_list.append(stats)

    # Step 5: Build output
    result: Dict[str, Any] = {}

    # Description
    result["_description"] = {
        "overview": "Critical path analysis - stats computed per unique trace path using trace_id stitching",
        "time_windows": {
            "pre": f"[pivot_time - {delta_time_str}, pivot_time)" if pivot_time else "N/A",
            "post": f"[pivot_time, pivot_time + {delta_time_str}]" if pivot_time else "All data",
        },
        "thresholds": {"error_rate_change_pct": error_threshold, "latency_change_pct": latency_threshold},
        "note": "Each path groups traces that follow the same service chain. Stats are computed from spans within those specific traces.",
    }

    # Warnings
    warnings = []
    if not pivot_time:
        warnings.append(
            "pivot_time not provided - comparative analysis disabled. "
            "Providing pivot_time is highly encouraged for incident investigation."
        )
    if warnings:
        result["warnings"] = warnings

    # Summary (aggregate across all paths)
    if pivot_time:
        total_pre = {"count": 0, "errors": 0, "latencies": []}
        total_post = {"count": 0, "errors": 0, "latencies": []}
        for ps in path_stats_list:
            total_pre["count"] += ps["pre"]["count"]
            total_pre["errors"] += ps["pre"]["errors"]
            total_pre["latencies"].extend(ps["pre"]["latencies"])
            total_post["count"] += ps["post"]["count"]
            total_post["errors"] += ps["post"]["errors"]
            total_post["latencies"].extend(ps["post"]["latencies"])

        pre_err_pct = (total_pre["errors"] / total_pre["count"] * 100) if total_pre["count"] > 0 else 0
        post_err_pct = (total_post["errors"] / total_post["count"] * 100) if total_post["count"] > 0 else 0

        result["summary"] = {
            "pre": (
                {
                    "trace_count": sum(len(pg["trace_ids"]) for pg in path_groups.values()),
                    "span_count": total_pre["count"],
                    "error_rate_pct": round(pre_err_pct, 1),
                    "latency_p99_ms": _compute_percentiles(total_pre["latencies"])["p99"],
                }
                if total_pre["count"] > 0
                else None
            ),
            "post": (
                {
                    "trace_count": sum(len(pg["trace_ids"]) for pg in path_groups.values()),
                    "span_count": total_post["count"],
                    "error_rate_pct": round(post_err_pct, 1),
                    "latency_p99_ms": _compute_percentiles(total_post["latencies"])["p99"],
                }
                if total_post["count"] > 0
                else None
            ),
        }

    # Step 6: Classify and format paths
    all_paths_formatted = []
    critical_paths = []

    for ps in path_stats_list:
        path_key = ps["path_key"]
        pre = ps["pre"]
        post = ps["post"]

        severity, is_critical = _classify_severity(pre, post, error_threshold, latency_threshold)

        # Format path with rate
        post_rate = post["count"] / window_duration_sec if window_duration_sec > 0 else 0
        path_str = f"{path_key} [{_format_rate(post_rate)}]"

        if severity:
            path_str += f" ({severity})"

        all_paths_formatted.append(path_str)

        # Build critical path detail
        if is_critical and pivot_time:
            hops = []
            for svc in ps["services"]:
                svc_stats = ps["service_stats"].get(svc, {"pre": {}, "post": {}})
                s_pre = svc_stats["pre"]
                s_post = svc_stats["post"]

                h_pre_count = s_pre.get("count", 0)
                h_post_count = s_post.get("count", 0)
                h_pre_err = (s_pre.get("errors", 0) / h_pre_count * 100) if h_pre_count > 0 else 0
                h_post_err = (s_post.get("errors", 0) / h_post_count * 100) if h_post_count > 0 else 0
                h_pre_lat = _compute_percentiles(s_pre.get("latencies", []))
                h_post_lat = _compute_percentiles(s_post.get("latencies", []))

                h_pre_rate = h_pre_count / window_duration_sec if window_duration_sec > 0 else 0
                h_post_rate = h_post_count / window_duration_sec if window_duration_sec > 0 else 0

                hops.append(
                    {
                        "service": svc,
                        "traffic": f"{_format_rate(h_pre_rate)} → {_format_rate(h_post_rate)}",
                        "error_rate": f"{h_pre_err:.0f}% → {h_post_err:.0f}%",
                        "latency_p99": f"{_format_latency(h_pre_lat['p99'])} → {_format_latency(h_post_lat['p99'])}",
                    }
                )

            critical_path = {
                "path": path_key,
                "severity": severity,
                "hops": hops,
                "sample_errors": list(ps.get("error_messages", set()))[:3],
            }

            # Find root cause - service with highest post error rate
            max_err_svc = None
            max_err_rate = 0
            for hop in hops:
                post_err_str = hop["error_rate"].split(" → ")[1]
                post_err = float(post_err_str.replace("%", ""))
                if post_err > max_err_rate and post_err > 50:
                    max_err_rate = post_err
                    max_err_svc = hop["service"]

            if max_err_svc:
                critical_path["root_cause_suspect"] = {
                    "service": max_err_svc,
                    "reason": f"{max_err_rate:.0f}% error rate",
                }

            critical_paths.append(critical_path)

    # Sort paths: critical first
    def path_sort_key(p):
        if "(CRITICAL)" in p:
            return 0
        elif "(WARNING)" in p:
            return 1
        elif "(NEW)" in p:
            return 2
        elif "(DISAPPEARED)" in p:
            return 3
        else:
            return 4

    all_paths_formatted.sort(key=path_sort_key)

    result["all_paths"] = all_paths_formatted[:50]

    critical_paths.sort(key=lambda x: 0 if x["severity"] == "CRITICAL" else 1)
    result["critical_paths"] = critical_paths

    result["filters_applied"] = {
        "service_name": service_name,
        "span_kind": span_kind_filter,
        "pivot_time": pivot_time_str,
        "delta_time": delta_time_str if pivot_time_str else None,
        "error_threshold_pct": error_threshold,
        "latency_threshold_pct": latency_threshold,
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]
