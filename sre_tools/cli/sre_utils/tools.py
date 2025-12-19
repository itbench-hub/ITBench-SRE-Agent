"""
SRE utility tool implementations.

These tools help with incident investigation by parsing and analyzing
Kubernetes events, metrics, and alerts, and building operational topologies.

Can be run as:
- MCP server: python -m sre_tools.cli.sre_utils
- CLI tool: python -m sre_tools.cli.sre_utils.tools --arch-file ... --k8s-objects-file ... --output-file ...
- Python API: from sre_tools.cli.sre_utils.tools import build_topology_standalone
"""

import csv
import json
import ast
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, List, Dict

try:
    import pandas as pd
    import numpy as np
except ImportError:
    pd = None
    np = None

try:
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
    from drain3.masking import MaskingInstruction
except ImportError:
    TemplateMiner = None
    TemplateMinerConfig = None
    MaskingInstruction = None

from mcp.server import Server
from mcp.types import Tool, TextContent

from sre_tools.utils import read_tsv_file, read_json_file, format_timestamp, truncate_string


def register_tools(server: Server) -> None:
    """Register all SRE utility tools with the MCP server.
    
    Args:
        server: The MCP Server instance to register tools with.
    """
    
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the list of available tools."""
        return [
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
                            "description": "Path to application architecture JSON file (e.g., otel_demo_application_architecture.json)"
                        },
                        "k8s_objects_file": {
                            "type": "string",
                            "description": "Path to Kubernetes objects TSV file (e.g., k8s_objects.tsv)"
                        },
                        "output_file": {
                            "type": "string",
                            "description": "Path to write the topology JSON output (e.g., operational_topology.json)"
                        }
                    },
                    "required": ["arch_file", "k8s_objects_file", "output_file"]
                }
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
                            "description": "Path to topology JSON file (e.g., operational_topology.json, output from build_topology)"
                        },
                        "entity": {
                            "type": "string",
                            "description": "Entity to analyze (name or partial match, e.g., 'checkout', 'flagd', 'frontend')"
                        }
                    },
                    "required": ["topology_file", "entity"]
                }
            ),
            Tool(
                name="metric_analysis",
                description="Analyzes metrics for K8s objects. Supports batch queries, derived metrics (eval), grouping, and aggregation. "
                            "Works like SQL/Pandas: filter -> eval -> group_by -> agg. "
                            "Example: CPU throttle % per deployment: object_pattern='pod/*', "
                            "metric_names=['container_cpu_cfs_throttled_periods_total', 'container_cpu_cfs_periods_total'], "
                            "eval='throttle_pct = container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total * 100', "
                            "group_by='deployment', agg='max'. "
                            "Example: Peak cluster memory %: object_pattern='pod/*', "
                            "metric_names=['container_memory_usage_bytes', 'cluster:namespace:pod_memory:active:kube_pod_container_resource_limits'], "
                            "eval='mem_pct = container_memory_usage_bytes / cluster_namespace_pod_memory_active_kube_pod_container_resource_limits * 100', "
                            "agg='max'. "
                            "Metric names with special chars are AUTO-SANITIZED (: -> _). "
                            "Tip: group_by='timestamp' for time series, group_by='deployment' for per-deployment.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "base_dir": {
                            "type": "string",
                            "description": "Path to metrics directory (e.g., metrics/) containing pod_*.tsv and service_*.tsv files"
                        },
                        "k8_object_name": {
                            "type": "string",
                            "description": "Optional: Specific K8s object (format '<kind>/<name>'). Omit to analyze ALL objects."
                        },
                        "object_pattern": {
                            "type": "string",
                            "description": "Optional: Glob pattern for objects (e.g., 'pod/*', 'pod/frontend*', 'service/*'). Default: '*' (all)"
                        },
                        "metric_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional: List of metric names to load. If omitted, loads all metrics."
                        },
                        "eval": {
                            "type": "string",
                            "description": "Optional: Pandas eval string for derived metrics (e.g. 'throttling_pct = throttled / total * 100')"
                        },
                        "filters": {
                             "type": "object",
                             "description": "Optional: Dictionary of exact matches for columns"
                        },
                        "group_by": {
                            "type": "string",
                            "description": "Optional: Column to group by. Special values: 'deployment' (auto-extracted from pod name), 'pod_name', 'metric_name'"
                        },
                        "agg": {
                            "type": "string",
                            "description": "Optional: Aggregation function (mean, sum, max, min). Default: mean"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC)."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC)."
                        },
                        "verbosity": {
                            "type": "string",
                            "description": "Optional: Output verbosity. 'compact' is optimized for LLMs (drops buckets by default, filters tags->labels, dedupes, applies limit). Use 'raw' for the full row output.",
                            "default": "compact",
                            "enum": ["compact", "raw"]
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max number of rows to return in compact mode. Use 0 for no limit.",
                            "default": 200
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Optional: Column to sort by (descending) before applying limit in compact mode."
                        },
                        "include_tags": {
                            "type": "boolean",
                            "description": "Optional: Keep the original verbose `tags` column in compact mode. Default: false (drop tags and emit filtered `labels` instead).",
                            "default": False
                        },
                        "include_buckets": {
                            "type": "boolean",
                            "description": "Optional: Include histogram bucket metrics (metric_name ending with '_bucket') in compact mode. Default: false.",
                            "default": False
                        },
                        "labels_keep": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional: Allowlist of tag keys to keep in the emitted `labels` field (compact mode)."
                        }
                    },
                    "required": ["base_dir"]
                }
            ),
            Tool(
                name="get_metric_anomalies",
                description="Reads and returns metrics and anomalies associated with a K8s object. "
                            "Use this to check for CPU spikes, memory leaks, or error rate increases. "
                            "Tip: Use metric_analysis first to identify relevant metric names. "
                            "Example: Check for CPU throttling: metric_name_filter='throttled'. "
                            "Example: Check for anomalies only: raw_content=False.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "k8_object_name": {
                            "type": "string",
                            "description": "Name of the K8s object (format '<kind>/<name>', e.g., 'pod/my-pod')"
                        },
                        "base_dir": {
                            "type": "string",
                            "description": "Path to metrics directory (e.g., metrics/) containing pod_*.tsv and service_*.tsv files"
                        },
                        "metric_name_filter": {
                            "type": "string",
                            "description": "Optional: Only analyze metrics matching this name/substring"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC)."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Can only be given if start_time is present. Examples: '2025-12-12T02:45:00Z' (UTC)."
                        },
                        "raw_content": {
                            "type": "boolean",
                            "description": "Optional: Include raw metric time series data (default: true)",
                            "default": True
                        }
                    },
                    "required": ["k8_object_name", "base_dir"]
                }
            ),
            Tool(
                name="event_analysis",
                description="Analyzes Kubernetes events. Works like SQL: filter → group_by → agg. "
                            "Supports multi-column grouping and multiple aggregation types. "
                            "Example: Event count by reason: group_by='reason' (find Unhealthy, Killing, Failed). "
                            "Example: Warnings per deployment: filters={'event_kind': 'Warning'}, group_by='deployment'. "
                            "Example: Events per namespace and reason: group_by=['namespace', 'reason']. "
                            "Example: First event per pod: group_by='object_name', agg='first'. "
                            "Tip: Use group_by='deployment' to auto-extract deployment from pod names. "
                            "Aggregations: 'count' (default), 'first', 'last', 'nunique', 'list'.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "events_file": {
                            "type": "string",
                            "description": "Path to Kubernetes events TSV file (e.g., k8s_events.tsv)"
                        },
                        "filters": {
                             "type": "object",
                             "description": "Optional: Column filters (e.g. {'reason': 'Unhealthy', 'event_kind': 'Warning', 'namespace': 'otel-demo'})"
                        },
                        "group_by": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}}
                            ],
                            "description": "Optional: Column(s) to group by. String or list. Special: 'deployment' extracts from pod names."
                        },
                        "agg": {
                            "type": "string",
                            "description": "Optional: Aggregation type - 'count' (default), 'first', 'last', 'nunique', 'list'"
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Optional: Column to sort by. Default: 'count' desc for grouped, 'timestamp' for raw."
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max rows to return. Use 0 to fetch all rows (no limit). Default: no limit."
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N rows (pagination). Default: 0"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC). Use 'Z' suffix or explicit timezone offset for clarity."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC). Use 'Z' suffix or explicit timezone offset for clarity."
                        }
                    },
                    "required": ["events_file"]
                }
            ),
            Tool(
                name="log_analysis",
                description="Analyzes application logs from OTEL log files with LOG PATTERN MINING. "
                            "By default (pattern_analysis=true), clusters logs into patterns using logmine and returns: "
                            "pattern template, count, severity breakdown, time range, and example log for each pattern. "
                            "This is ideal for SRE investigation - see high-level patterns instead of scrolling through logs. "
                            "Set pattern_analysis=false for raw log pagination. "
                            "Example: Get patterns for a service: k8_object='Deployment/recommendation'. "
                            "Example: Get error patterns: severity_filter='ERROR'. "
                            "Example: Search patterns: body_contains='timeout'.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "logs_file": {
                            "type": "string",
                            "description": "Path to OTEL logs TSV file (e.g., otel_logs_raw.tsv)"
                        },
                        "k8_object": {
                            "type": "string",
                            "description": "Optional: K8s object in Kind/name format (e.g., 'Deployment/recommendation', 'Pod/cart-xxx'). Matches against k8s.deployment.name or k8s.pod.name in ResourceAttributes."
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Optional: Filter by ServiceName column (e.g., 'recommendation', 'cart')"
                        },
                        "severity_filter": {
                            "type": "string",
                            "description": "Optional: Filter by SeverityText (e.g., 'ERROR', 'WARNING', 'INFO'). Can be comma-separated for multiple: 'ERROR,WARNING'"
                        },
                        "body_contains": {
                            "type": "string",
                            "description": "Optional: Case-insensitive substring search in log Body"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format (e.g., '2025-12-15T17:15:00Z')"
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format (e.g., '2025-12-15T17:35:00Z')"
                        },
                        "pattern_analysis": {
                            "type": "boolean",
                            "description": "Optional: Enable log pattern mining (default: true). When true, clusters logs into patterns with counts and examples. When false, returns raw logs with pagination.",
                            "default": True
                        },
                        "max_patterns": {
                            "type": "integer",
                            "description": "Optional: Maximum patterns to return when pattern_analysis=true. Default: 50. Patterns are sorted by count (most frequent first)."
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "description": "Optional: Similarity threshold for pattern clustering (0.0-1.0). Lower values create more specific patterns. Default: 0.5"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max rows to return (only when pattern_analysis=false). Default: 100. Use 0 for no limit."
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N rows (only when pattern_analysis=false). Default: 0"
                        }
                    },
                    "required": ["logs_file"]
                }
            ),
            Tool(
                name="get_trace_error_tree",
                description="Analyzes distributed traces to find critical paths with regressions. "
                            "Returns a compact output: all_paths (quick overview with traffic rates) and critical_paths (detailed analysis of degraded paths only). "
                            "Paths with changes below thresholds are omitted from detailed analysis. "
                            "Shows full lineage (upstream callers) for each service. "
                            "Example: Compare before/after an incident: pivot_time='2023-10-27T10:00:00Z', delta_time='5m'. "
                            "Example: Focus on checkout service: service_name='checkout'.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "trace_file": {
                            "type": "string",
                            "description": "Path to OpenTelemetry traces TSV file (e.g., otel_traces.tsv)"
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Optional: Filter to only include traces that CONTAIN this service (shows full lineage including upstream callers)"
                        },
                        "span_kind": {
                            "type": "string",
                            "description": "Optional: Filter spans by kind (Client, Server, Internal).",
                            "enum": ["Client", "Server", "Internal"]
                        },
                        "pivot_time": {
                            "type": "string",
                            "description": "Highly recommended: Pivot timestamp for before/after comparison (ISO 8601). Required for regression analysis."
                        },
                        "delta_time": {
                            "type": "string",
                            "description": "Optional: Duration for comparison window (e.g., '5m', '10m', '1h'). Default: 5m",
                            "default": "5m"
                        },
                        "error_threshold_pct": {
                            "type": "number",
                            "description": "Optional: Only show paths where error rate changed by more than this percentage. Default: 10",
                            "default": 10
                        },
                        "latency_threshold_pct": {
                            "type": "number",
                            "description": "Optional: Only show paths where latency changed by more than this percentage. Default: 10",
                            "default": 10
                        }
                    },
                    "required": ["trace_file"]
                }
            ),
            Tool(
                name="alert_analysis",
                description="Analyzes alerts. Works like SQL: filter → group_by → agg. "
                            "Computes duration_active (how long alert has been firing). "
                            "Example: Alert count by type: group_by='alertname'. "
                            "Example: Firing alerts by severity: filters={'state': 'firing'}, group_by='severity'. "
                            "Example: Alerts per service: group_by='service_name'. "
                            "Example: Long-running alerts: filters={'state': 'firing'}, sort_by='duration_active_min'. "
                            "Column shortcuts: 'alertname', 'severity', 'service_name', 'namespace' (maps to labels.*). "
                            "Aggregations: 'count' (default), 'first', 'last', 'sum', 'mean', 'max', 'min'.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "base_dir": {
                            "type": "string",
                            "description": "Path to alerts directory (e.g., alerts/) containing alerts_at_*.json files, OR snapshot directory (auto-detects 'alerts/' subdirectory)"
                        },
                        "time_basis": {
                            "type": "string",
                            "description": "Optional: Which timestamp to use for time window filtering and default ordering. "
                                           "'snapshot' uses observation time (API response timestamp or alerts_at_* filename). "
                                           "'activeAt' uses when the alert first became active in Alertmanager/Prometheus. "
                                           "Default: snapshot.",
                            "enum": ["snapshot", "activeAt"],
                            "default": "snapshot"
                        },
                        "filters": {
                             "type": "object",
                             "description": "Optional: Column filters (e.g. {'state': 'firing', 'severity': 'critical'})"
                        },
                        "group_by": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}}
                            ],
                            "description": "Optional: Column(s) to group by. Shortcuts: alertname, severity, service_name, namespace."
                        },
                        "agg": {
                            "type": "string",
                            "description": "Optional: Aggregation - 'count' (default), 'first', 'last', 'sum', 'mean', 'max', 'min'"
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Optional: Column to sort by (e.g. 'duration_active_min', 'count')"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max rows to return. Use 0 to fetch all rows (no limit). Default: no limit."
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N rows (pagination). Default: 0"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Filter alerts after this time (ISO 8601). "
                                           "By default this applies to snapshot/observation time (time_basis='snapshot'). "
                                           "Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC)."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: Filter alerts before this time (ISO 8601). "
                                           "By default this applies to snapshot/observation time (time_basis='snapshot'). "
                                           "Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC)."
                        }
                    },
                    "required": ["base_dir"]
                }
            ),
            Tool(
                name="alert_summary",
                description="Provides a high-level summary of all alerts: alert type, affected entity, time range, duration, and frequency. "
                            "Use this FIRST to get an overview before diving into specific alerts with alert_analysis. "
                            "Returns: alertname, entity (service/pod), severity, state, first_seen, last_seen, duration_min, occurrence_count. "
                            "NOTE: first_seen/last_seen are based on snapshot/observation time (not activeAt). "
                            "Sorted by duration (longest-running alerts first).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "base_dir": {
                            "type": "string",
                            "description": "Path to alerts directory (e.g., alerts/) containing alerts_at_*.json files, OR snapshot directory (auto-detects 'alerts/' subdirectory)"
                        },
                        "time_basis": {
                            "type": "string",
                            "description": "Optional: Which timestamp to use for first_seen/last_seen/duration_min. "
                                           "'snapshot' uses observation time (recommended). "
                                           "'activeAt' uses when the alert first became active. Default: snapshot.",
                            "enum": ["snapshot", "activeAt"],
                            "default": "snapshot"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp (ISO 8601) for filtering. "
                                           "Applies to snapshot time by default (time_basis='snapshot')."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp (ISO 8601) for filtering. "
                                           "Applies to snapshot time by default (time_basis='snapshot')."
                        },
                        "state_filter": {
                            "type": "string",
                            "description": "Optional: Filter by state ('firing', 'pending', 'inactive'). Default: show all."
                        },
                        "min_duration_min": {
                            "type": "number",
                            "description": "Optional: Only show alerts active for at least this many minutes"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max alerts to return. Default: 50"
                        }
                    },
                    "required": ["base_dir"]
                }
            ),
            Tool(
                name="k8s_spec_change_analysis",
                description="Analyzes Kubernetes object spec changes over time. "
                            "Detects and reports meaningful spec changes, filtering out timestamp-related churn. "
                            "Groups by entity, computes diffs between consecutive specs, and reports duration. "
                            "Example: Find all spec changes: k8s_objects_file='k8s_objects.tsv'. "
                            "Example: Changes to a specific deployment: k8_object_name='Deployment/cart'. "
                            "Example: Changes in time window: start_time='2025-12-01T21:00:00Z', end_time='2025-12-01T22:00:00Z'. "
                            "Useful for: identifying config drift, tracking rollouts, correlating incidents with changes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "k8s_objects_file": {
                            "type": "string",
                            "description": "Path to Kubernetes objects TSV file (e.g., k8s_objects.tsv)"
                        },
                        "k8_object_name": {
                            "type": "string",
                            "description": "Optional: Filter by specific object (format 'Kind/name', e.g., 'Deployment/cart', 'Pod/frontend-xyz')"
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC)."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Requires start_time. Examples: '2025-12-12T02:45:00Z' (UTC)."
                        },
                        "max_changes_per_diff": {
                            "type": "integer",
                            "description": "Optional: Cap the number of change items returned per diff window. If omitted, returns all change items (can be large)."
                        },
                        "include_reference_spec": {
                            "type": "boolean",
                            "description": "Optional: Include the baseline (reference) spec used for diffing. Default: true."
                        },
                        "include_flat_change_items": {
                            "type": "boolean",
                            "description": "Optional: Include a flat list of all change items (path/type/old/new) with timestamps for easier programmatic consumption. Default: true."
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max number of entities with changes to return (pagination)"
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N entities (pagination). Default: 0"
                        },
                        "include_no_change": {
                            "type": "boolean",
                            "description": "Optional: Include entities with no spec changes (default: false)"
                        }
                    },
                    "required": ["k8s_objects_file"]
                }
            ),
            Tool(
                name="get_context_contract",
                description="Aggregates full operational context for a K8s entity by calling multiple analysis tools. "
                            "Returns: events, alerts, trace errors, metric anomalies, K8s object definition, spec changes, "
                            "and dependency context. Uses existing tools internally (topology_analysis, event_analysis, etc.). "
                            "Example: Get full context for a service: k8_object='Service/cart', snapshot_dir='/path/to/snapshot'. "
                            "Example: With time window: start_time='2025-12-01T21:00:00Z', end_time='2025-12-01T22:00:00Z'. "
                            "Pagination: page=1 returns main entity context, page=2+ returns dependency context.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "k8_object": {
                            "type": "string",
                            "description": "K8s object in Kind/name format (e.g., 'Deployment/cart', 'Service/frontend', 'Pod/cart-xyz')"
                        },
                        "snapshot_dir": {
                            "type": "string",
                            "description": "Path to snapshot directory containing k8s_events.tsv, k8s_objects.tsv, otel_traces.tsv, alerts/, metrics/"
                        },
                        "topology_file": {
                            "type": "string",
                            "description": "Optional: Path to topology JSON file (e.g., operational_topology.json). If not provided, will look in snapshot_dir or build one."
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC)."
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC)."
                        },
                        "page": {
                            "type": "integer",
                            "description": "Optional: Page number. Page 0 = ALL pages at once, Page 1 = main entity, Page 2+ = dependencies. Default: 1"
                        },
                        "deps_per_page": {
                            "type": "integer",
                            "description": "Optional: Number of dependencies per page (for page >= 2). Default: 3. Ignored if page=0."
                        }
                    },
                    "required": ["k8_object", "snapshot_dir"]
                }
            ),
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle tool invocations."""
        
        if name == "build_topology":
            return await _build_topology(arguments)
        elif name == "topology_analysis":
            return await _topology_analysis(arguments)
        elif name == "metric_analysis":
            return await _metric_analysis(arguments)
        elif name == "get_metric_anomalies":
            return await _get_metric_anomalies(arguments)
        elif name == "event_analysis":
            return await _event_analysis(arguments)
        elif name == "log_analysis":
            return await _log_analysis(arguments)
        elif name == "get_trace_error_tree":
            return await _get_trace_error_tree(arguments)
        elif name == "alert_analysis":
            return await _alert_analysis(arguments)
        elif name == "alert_summary":
            return await _alert_summary(arguments)
        elif name == "k8s_spec_change_analysis":
            return await _k8s_spec_change_analysis(arguments)
        elif name == "get_context_contract":
            return await _get_context_contract(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


# =============================================================================
# Helper Functions
# =============================================================================

def _parse_time(ts: str) -> datetime:
    """Parse timestamp string to datetime object."""
    try:
        # Handle ISO format with Z
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        # Try other formats if needed
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
             return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

def _extract_alert_snapshot_timestamp(json_file: Path, data: Any) -> Optional[str]:
    """Extract observation/snapshot timestamp for an alerts JSON file.
    
    For alert snapshot dumps, we want *when the alert was observed* (the snapshot time),
    not when it first became active (activeAt).
    
    Supported formats:
    - alerts_at_YYYY-MM-DDTHH-MM-SS[.ffffff].json (timestamp comes from filename)
    - alerts_in_alerting_state_*.json (timestamp often exists in JSON as top-level 'timestamp')
    
    Returns an ISO-8601 string with 'Z' suffix when possible.
    """
    if isinstance(data, dict):
        ts = data.get("timestamp")
        if isinstance(ts, str) and ts.strip():
            return ts.strip()

    stem = json_file.stem

    # alerts_at_2025-12-15T18-17-09.387695.json
    m = re.search(
        r"alerts_at_(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})(\.\d+)?",
        stem,
    )
    if m:
        date, hh, mm, ss, frac = m.groups()
        frac = frac or ""
        return f"{date}T{hh}:{mm}:{ss}{frac}Z"

    # alerts_in_alerting_state_2025-12-15T175546.713186Z.json
    m = re.search(
        r"alerts_in_alerting_state_(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})(\.\d+)?Z?",
        stem,
    )
    if m:
        date, hh, mm, ss, frac = m.groups()
        frac = frac or ""
        return f"{date}T{hh}:{mm}:{ss}{frac}Z"

    # Fallback: try to find any YYYY-MM-DDT... token and normalize.
    m = re.search(r"(\d{4}-\d{2}-\d{2})T([^_]+)", stem)
    if not m:
        return None

    date, tail = m.groups()
    tail = tail.rstrip("Z")

    # If the tail uses hyphens as separators: 18-17-09.387695
    if "-" in tail:
        parts = tail.split(".", 1)
        hms = parts[0].replace("-", ":")
        frac = f".{parts[1]}" if len(parts) == 2 and parts[1] else ""
        if len(hms.split(":")) == 3:
            return f"{date}T{hms}{frac}Z"

    # If the tail is a compact time: 175546.713186
    parts = tail.split(".", 1)
    digits = parts[0]
    if digits.isdigit() and len(digits) >= 6:
        hms = f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
        frac = f".{parts[1]}" if len(parts) == 2 and parts[1] else ""
        return f"{date}T{hms}{frac}Z"

    return None

def _to_utc_timestamp(ts) -> "pd.Timestamp":
    """Convert a time value to UTC-aware pandas Timestamp for comparison.
    
    Handles both timezone-aware and timezone-naive inputs consistently.
    All timestamps are treated as UTC for comparison purposes.
    """
    ts_pd = pd.Timestamp(ts)
    if ts_pd.tzinfo is None:
        return ts_pd.tz_localize('UTC')
    else:
        return ts_pd.tz_convert('UTC')

def _parse_duration(duration_str: str) -> timedelta:
    """Parse duration string (e.g., '5m', '1h') to timedelta."""
    if not duration_str:
        return timedelta(minutes=5)
    
    unit = duration_str[-1]
    value = int(duration_str[:-1])
    
    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    else:
        return timedelta(minutes=5)  # Default


def _filter_by_time(
    records: List[Dict[str, Any]], 
    time_col: str, 
    start: datetime, 
    end: datetime
) -> List[Dict[str, Any]]:
    """Filter records by time range [start, end)."""
    result = []
    for record in records:
        ts_str = record.get(time_col)
        if not ts_str:
            continue
        try:
            ts = _parse_time(ts_str)
            # Make both timezone-aware or both naive for comparison
            if ts.tzinfo is None and start.tzinfo is not None:
                ts = ts.replace(tzinfo=start.tzinfo)
            elif ts.tzinfo is not None and start.tzinfo is None:
                ts = ts.replace(tzinfo=None)
            if start <= ts < end:
                result.append(record)
        except (ValueError, TypeError):
            continue
    return result


# =============================================================================
# Build Topology Tool Implementation
# =============================================================================

def _obj_id(kind: str, name: str, namespace: Optional[str] = None) -> str:
    """Generate a simple, consistent object ID: Kind/name."""
    return f"{kind}/{name}"


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
        "ad-service": "ad", "cart-service": "cart", "checkout-service": "checkout",
        "currency-service": "currency", "product-catalog-service": "product-catalog",
        "recommendation-service": "recommendation", "shipping-service": "shipping",
        "product-reviews-service": "product-reviews", "email-service": "email",
        "payment-service": "payment", "quote-service": "quote", "valkey": "valkey-cart",
        "frontend-proxy": "frontend-proxy", "load-generator": "load-generator",
        "frontend": "frontend", "kafka": "kafka", "postgresql": "postgresql",
        "accounting-service": "accounting", "fraud-detection-service": "fraud-detection",
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
        return [TextContent(type="text", text=f"Error: Topology file not found: {topology_file}. "
                                              f"Build it first with build_topology tool.")]
    
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

def _extract_deployment_from_pod(pod_name: str) -> str:
    """Extract deployment name from pod name.
    
    Kubernetes pod naming convention: <deployment>-<replicaset-hash>-<pod-hash>
    e.g., frontend-675fd7b5c5-gd8gl -> frontend
          checkout-8546fdc74d-7m4dn -> checkout
    """
    if not pod_name:
        return "unknown"
    parts = pod_name.rsplit("-", 2)
    if len(parts) >= 3:
        return parts[0]
    elif len(parts) == 2:
        return parts[0]
    return pod_name


def _sanitize_metric_name(name: str) -> str:
    """Sanitize metric name to be valid Python/Pandas identifier.
    
    Replaces special characters with underscores so metric names can be used
    in eval expressions.
    
    e.g., cluster:namespace:pod_memory:active:kube_pod_container_resource_limits
          -> cluster_namespace_pod_memory_active_kube_pod_container_resource_limits
    """
    import re
    # Replace colons, dots, dashes, and other special chars with underscores
    sanitized = re.sub(r'[:\-\./\s]', '_', name)
    # Remove consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized


def _sanitize_eval_query(eval_query: str, name_mapping: dict[str, str]) -> str:
    """Transform eval query to use sanitized metric names.
    
    If the user wrote an eval using original metric names (with colons),
    automatically transform it to use sanitized names.
    """
    result = eval_query
    # Sort by length descending to replace longer names first (avoid partial matches)
    for original, sanitized in sorted(name_mapping.items(), key=lambda x: -len(x[0])):
        if original != sanitized:
            result = result.replace(original, sanitized)
    return result


def _extract_object_info_from_filename(filename: str) -> dict[str, str]:
    """Extract object kind and name from metric filename.
    
    Filename format: <kind>_<name>.tsv
    e.g., pod_checkout-8546fdc74d-7m4dn.tsv -> {"kind": "pod", "name": "checkout-8546fdc74d-7m4dn"}
    """
    stem = filename.replace(".tsv", "")
    parts = stem.split("_", 1)
    if len(parts) == 2:
        return {"kind": parts[0], "name": parts[1]}
    return {"kind": "unknown", "name": stem}

def _parse_tags_to_dict(tags: Any) -> dict[str, Any]:
    """Parse the `tags` column into a dict.

    Metrics TSVs may store tags as:
    - a dict-like string: "{'k': 'v', ...}"
    - a JSON object string: '{"k":"v"}'
    - already a dict
    """
    if tags is None:
        return {}
    if isinstance(tags, dict):
        return tags
    if not isinstance(tags, str):
        return {}

    s = tags.strip()
    if not s:
        return {}

    # Try JSON first.
    if s.startswith("{") and '"' in s:
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

    # Fallback to python-literal style (repr(dict)).
    try:
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _filter_labels(labels: dict[str, Any], keep: list[str] | None) -> dict[str, Any]:
    """Filter label dict to allowlisted keys."""
    if not labels or not keep:
        return {}
    return {k: labels[k] for k in keep if k in labels}


def _df_to_json_records(df: "pd.DataFrame", *, compact: bool) -> str:
    """Serialize a DataFrame to JSON records.

    Compact mode is intended for LLM consumption (no pretty indentation).
    """
    if compact:
        return df.to_json(orient="records")
    return df.to_json(orient="records", indent=2)

def _prom_histogram_quantile(q: float, buckets: list[tuple[float, float]]) -> float | None:
    """Approximate Prometheus-style histogram_quantile for cumulative buckets.

    buckets: list of (le, cumulative_count), sorted by le.
    """
    if not buckets:
        return None

    # Ensure sorted and clean.
    buckets = [(le, cnt) for le, cnt in buckets if le is not None and cnt is not None]
    buckets.sort(key=lambda x: x[0])
    if not buckets:
        return None

    total = buckets[-1][1]
    try:
        total_f = float(total)
    except Exception:
        return None

    if total_f <= 0:
        return None

    rank = q * total_f
    prev_le = 0.0
    prev_cnt = 0.0

    for le, cnt in buckets:
        try:
            le_f = float(le)
            cnt_f = float(cnt)
        except Exception:
            continue

        if cnt_f >= rank:
            # If this is the +Inf bucket, return the previous boundary.
            if le_f == float("inf"):
                return prev_le

            bucket_cnt = cnt_f - prev_cnt
            if bucket_cnt <= 0:
                return le_f

            return prev_le + (le_f - prev_le) * ((rank - prev_cnt) / bucket_cnt)

        prev_le = le_f
        prev_cnt = cnt_f

    # Should not happen if last bucket is +Inf, but be defensive.
    return buckets[-1][0]


async def _metric_analysis(args: dict[str, Any]) -> list[TextContent]:
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    base_dir = args.get("base_dir", "")
    k8_object_name = args.get("k8_object_name")  # Now optional
    object_pattern = args.get("object_pattern", "*")  # Default: all objects
    metric_names = args.get("metric_names", [])
    eval_query = args.get("eval")
    filters = args.get("filters", {})
    group_by = args.get("group_by")
    agg_func = args.get("agg", "mean")
    verbosity = args.get("verbosity", "compact")  # "compact" | "raw"
    limit = int(args.get("limit", 200) or 0)      # 0 => no limit
    sort_by = args.get("sort_by")                 # optional column name to sort descending
    include_tags = bool(args.get("include_tags", False))
    include_buckets = bool(args.get("include_buckets", False))
    labels_keep = args.get("labels_keep") or [
        # High-signal OTEL spanmetrics labels
        "span_name",
        "span_kind",
        "status_code",
        # Histogram bucket label (only meaningful if include_buckets=True)
        "le",
    ]
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    
    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    # Normalize start/end bounds to naive UTC datetimes for consistent comparison
    start_bound = None
    end_bound = None
    if start_time:
        st = pd.Timestamp(start_time)
        if st.tzinfo is not None:
            st = st.tz_convert('UTC').tz_localize(None)
        start_bound = st.to_pydatetime()
    if end_time:
        et = pd.Timestamp(end_time)
        if et.tzinfo is not None:
            et = et.tz_convert('UTC').tz_localize(None)
        end_bound = et.to_pydatetime()
    
    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Metrics directory not found: {base_dir}")]
    
    # Determine which files to load
    if k8_object_name:
        # Specific object requested
        try:
            kind, name = k8_object_name.split("/", 1)
            # Try multiple name patterns to handle naming variations
            # e.g., "product-catalog-service" -> try "product-catalog-service", "product-catalog"
            name_variants = [name]
            for suffix in ["-service", "_service", "-svc", "_svc"]:
                if name.endswith(suffix):
                    name_variants.append(name[:-len(suffix)])
            
            files = []
            for variant in name_variants:
                prefix = f"{kind.lower()}_{variant}"
                files = list(base_path.glob(f"{prefix}*.tsv"))
                if files:
                    break
        except ValueError:
            return [TextContent(type="text", text="Invalid k8_object_name format. Use '<kind>/<name>'")]
    else:
        # Batch mode: use object_pattern
        # Convert "pod/*" to "pod_*.tsv", "pod/frontend*" to "pod_frontend*.tsv"
        if "/" in object_pattern:
            kind, name_pattern = object_pattern.split("/", 1)
            glob_pattern = f"{kind.lower()}_{name_pattern}.tsv"
        else:
            glob_pattern = f"{object_pattern}.tsv" if object_pattern != "*" else "*.tsv"
        
        files = list(base_path.glob(glob_pattern))
    
    if not files:
        return [TextContent(type="text", text=f"No metric files found matching pattern")]
    
    all_data = []
    
    for file_path in files:
        try:
            df = pd.read_csv(file_path, sep='\t')
            
            # Extract object info from filename and add as columns
            obj_info = _extract_object_info_from_filename(file_path.name)
            df['_source_file'] = file_path.name
            df['_object_kind'] = obj_info['kind']
            df['_object_name'] = obj_info['name']
            
            # Extract deployment from pod name
            if obj_info['kind'] == 'pod':
                df['deployment'] = _extract_deployment_from_pod(obj_info['name'])
            else:
                df['deployment'] = obj_info['name']
            
            # Filter by metric names if provided
            if metric_names:
                if 'metric_name' in df.columns:
                    df = df[df['metric_name'].isin(metric_names)]
            
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            
            # Time filter
            if start_time:
                df = df[df['timestamp'] >= _to_utc_timestamp(start_time)]
            if end_time:
                df = df[df['timestamp'] <= _to_utc_timestamp(end_time)]
            
            # Custom filters
            if filters:
                for col, val in filters.items():
                    if col in df.columns:
                        df = df[df[col] == val]
            
            if not df.empty:
                all_data.append(df)
                
        except Exception:
            continue
            
    if not all_data:
        return [TextContent(type="text", text="[]")]
        
    combined_df = pd.concat(all_data, ignore_index=True)

    compact_mode = verbosity != "raw"

    # =============================================================================
    # LLM-friendly output shaping (requested changes 1, 2, 4, 6)
    #
    # 1) Default away from raw rows: compact mode is default (verbosity="compact").
    # 2) Replace verbose `tags` with a small allowlisted `labels` dict.
    # 4) Dedupe duplicate rows.
    # 6) Hide histogram bucket metrics unless explicitly requested.
    # =============================================================================
    if compact_mode:
        # 6) Histogram buckets explode output and are hard for LLMs.
        # Default behavior:
        # - If user did NOT request bucket metrics: drop bucket rows entirely.
        # - If user DID request bucket metrics: compute p50/p90/p95/p99 from buckets (instead of returning raw buckets),
        #   unless include_buckets=True.
        requested_bucket_metrics = any(str(m).endswith("_bucket") for m in (metric_names or []))
        compute_bucket_quantiles = requested_bucket_metrics and not include_buckets
        if "metric_name" in combined_df.columns and not requested_bucket_metrics and not include_buckets:
            combined_df = combined_df[~combined_df["metric_name"].astype(str).str.endswith("_bucket")]

        # 2) Parse tags and keep only high-signal labels.
        if "tags" in combined_df.columns:
            parsed = combined_df["tags"].apply(_parse_tags_to_dict)
            combined_df["labels"] = parsed.apply(lambda d: _filter_labels(d, labels_keep))
            # For dedupe, use a stable, hashable signature (dicts are unhashable).
            combined_df["_labels_sig"] = combined_df["labels"].apply(
                lambda d: json.dumps(d, sort_keys=True, separators=(",", ":"))
            )
            # For bucket quantiles, group on labels WITHOUT `le`.
            combined_df["_labels_no_le_sig"] = combined_df["labels"].apply(
                lambda d: json.dumps({k: v for k, v in d.items() if k != "le"}, sort_keys=True, separators=(",", ":"))
            )
            if not include_tags:
                combined_df = combined_df.drop(columns=["tags"], errors="ignore")

        # 4) Dedupe after normalization.
        dedupe_cols = [
            c for c in [
                "timestamp",
                "metric_name",
                "metric_type",
                "namespace",
                "service_name",
                "status_code",
                "bucket_le",
                "value",
                "_labels_sig",
            ]
            if c in combined_df.columns
        ]
        if dedupe_cols:
            combined_df = combined_df.drop_duplicates(subset=dedupe_cols, keep="last")
        else:
            combined_df = combined_df.drop_duplicates(keep="last")

        # If bucket metrics were requested, compute quantiles and return compact rows (no raw buckets).
        if compute_bucket_quantiles and "metric_name" in combined_df.columns:
            bucket_df = combined_df[combined_df["metric_name"].astype(str).str.endswith("_bucket")]
            if not bucket_df.empty:
                # Convert bucket boundary to numeric, handling +Inf.
                if "bucket_le" in bucket_df.columns:
                    le_series = bucket_df["bucket_le"].astype(str)
                elif "labels" in bucket_df.columns:
                    le_series = bucket_df["labels"].apply(lambda d: d.get("le")).astype(str)
                else:
                    le_series = None

                if le_series is not None:
                    bucket_df = bucket_df.copy()
                    bucket_df["_le"] = pd.to_numeric(le_series.replace({"+Inf": "inf", "inf": "inf"}), errors="coerce")
                else:
                    bucket_df = bucket_df.copy()
                    bucket_df["_le"] = np.nan

                # Define grouping keys (exclude timestamp/le/value and internal columns).
                group_cols = [
                    c for c in bucket_df.columns
                    if c not in ("timestamp", "bucket_le", "_le", "value", "labels", "_labels_sig")
                    and not c.startswith("_")
                ]
                # Ensure labels grouping uses the no-le signature (avoid per-bucket duplication).
                if "_labels_no_le_sig" in bucket_df.columns and "_labels_no_le_sig" not in group_cols:
                    group_cols.append("_labels_no_le_sig")

                # Find the latest timestamp per group and compute quantiles at that timestamp.
                latest_ts = bucket_df.groupby(group_cols, dropna=False)["timestamp"].max().reset_index()
                bucket_latest = bucket_df.merge(latest_ts, on=group_cols + ["timestamp"], how="inner")

                out_rows: list[dict[str, Any]] = []
                for _, g in bucket_latest.groupby(group_cols, dropna=False):
                    # Build bucket list (le, cumulative_count).
                    buckets = list(zip(g["_le"].tolist(), pd.to_numeric(g["value"], errors="coerce").fillna(0.0).tolist()))
                    # Sort and compute.
                    p50 = _prom_histogram_quantile(0.50, buckets)
                    p90 = _prom_histogram_quantile(0.90, buckets)
                    p95 = _prom_histogram_quantile(0.95, buckets)
                    p99 = _prom_histogram_quantile(0.99, buckets)

                    # Use the +Inf bucket count as sample_count if present.
                    try:
                        sample_count = float(max(cnt for le, cnt in buckets if le == float("inf")))
                    except Exception:
                        sample_count = float(max(cnt for _, cnt in buckets)) if buckets else 0.0

                    base = {}
                    # Pull representative dimension columns from the first row.
                    first = g.iloc[0]
                    for c in group_cols:
                        if c == "_labels_no_le_sig":
                            continue
                        base[c] = first.get(c)

                    # Attach labels (no-le) back as dict.
                    if "_labels_no_le_sig" in g.columns:
                        try:
                            base["labels"] = json.loads(first.get("_labels_no_le_sig") or "{}")
                        except Exception:
                            base["labels"] = {}

                    base["timestamp"] = str(first.get("timestamp"))
                    base["sample_count"] = sample_count
                    base["duration_ms"] = {"p50": p50, "p90": p90, "p95": p95, "p99": p99}
                    out_rows.append(base)

                out_df = pd.DataFrame(out_rows)
                if sort_by and sort_by in out_df.columns:
                    out_df = out_df.sort_values(sort_by, ascending=False)
                if limit and len(out_df) > limit:
                    out_df = out_df.head(limit)

                return [TextContent(type="text", text=_df_to_json_records(out_df, compact=True))]
    
    # If eval is requested, we need to pivot so metrics are columns
    if eval_query:
        if 'metric_name' not in combined_df.columns or 'value' not in combined_df.columns:
             return [TextContent(type="text", text="Error: Cannot perform eval - missing metric_name or value columns")]
        
        # Build mapping of original metric names to sanitized names
        unique_metrics = combined_df['metric_name'].unique()
        name_mapping = {m: _sanitize_metric_name(m) for m in unique_metrics}
        sanitized_eval = _sanitize_eval_query(eval_query, name_mapping)
        
        # Detect mode based on group_by: per-object or cluster-wide
        per_object_mode = group_by in ('deployment', 'pod_name', '_object_name')
        
        try:
            if per_object_mode:
                # PER-OBJECT MODE: Compute derived metric at each timestamp FIRST, then aggregate
                # This ensures ratios like throttle_pct are computed correctly before aggregation
                pivot_dfs = []
                
                for obj_name, obj_df in combined_df.groupby('_object_name'):
                    # Pivot with timestamp index - keep all data points
                    pivot_df = obj_df.pivot_table(
                        index='timestamp',
                        columns='metric_name', 
                        values='value', 
                        aggfunc='mean'  # For duplicate timestamps, use mean
                    )
                    
                    # Forward-fill to handle misaligned timestamps
                    pivot_df = pivot_df.ffill().bfill()
                    pivot_df.columns = [_sanitize_metric_name(c) for c in pivot_df.columns]
                    
                    # Compute derived metric (e.g., throttle_pct) at each timestamp
                    pivot_df.eval(sanitized_eval, inplace=True)
                    
                    # Add object metadata
                    pivot_df = pivot_df.reset_index()
                    pivot_df['_object_name'] = obj_name
                    pivot_df['deployment'] = obj_df['deployment'].iloc[0] if 'deployment' in obj_df.columns else obj_name
                    pivot_df['pod_name'] = obj_name
                    pivot_dfs.append(pivot_df)
                
                combined_df = pd.concat(pivot_dfs, ignore_index=True)
            else:
                # CLUSTER-WIDE MODE: Sum across all objects at each timestamp, then compute derived metric
                pivot_df = combined_df.pivot_table(
                    index='timestamp',
                    columns='metric_name', 
                    values='value', 
                    aggfunc='sum'
                )
                
                # Forward-fill to handle misaligned timestamps
                pivot_df = pivot_df.ffill().bfill()
                pivot_df.columns = [_sanitize_metric_name(c) for c in pivot_df.columns]
                
                # Compute derived metric
                pivot_df.eval(sanitized_eval, inplace=True)
                
                if "=" not in sanitized_eval:
                    result = pivot_df.eval(sanitized_eval)
                    if isinstance(result, pd.Series):
                        pivot_df['result'] = result
                
                combined_df = pivot_df.reset_index()
            
        except Exception as e:
            sanitized_names = list(name_mapping.values())
            return [TextContent(type="text", text=f"Error in eval: {e}\n"
                                                  f"Available columns (sanitized): {sanitized_names}")]

    # 1) In compact mode, default to a summary rather than returning raw rows.
    # Users can still request time series via group_by="timestamp", or full raw output via verbosity="raw".
    if compact_mode and not group_by and not eval_query and agg_func == "mean":
        if "value" in combined_df.columns:
            # Treat all non-internal, non-value columns as dimensions; collapse timestamps.
            dim_cols = [
                c for c in combined_df.columns
                if c not in ("timestamp", "value") and not c.startswith("_")
            ]

            if dim_cols:
                used_label_sig = False
                # `labels` is a dict (unhashable) - use `_labels_sig` for grouping if available.
                if "labels" in dim_cols:
                    if "_labels_sig" in combined_df.columns:
                        dim_cols = ["_labels_sig" if c == "labels" else c for c in dim_cols]
                        used_label_sig = True
                    else:
                        # Fall back to a stable string representation for grouping.
                        combined_df["_labels_sig"] = combined_df["labels"].apply(
                            lambda d: json.dumps(d, sort_keys=True, separators=(",", ":"))
                        )
                        dim_cols = ["_labels_sig" if c == "labels" else c for c in dim_cols]
                        used_label_sig = True

                stats = (
                    combined_df.groupby(dim_cols, dropna=False)["value"]
                    .agg(count="count", mean="mean", min="min", max="max")
                    .reset_index()
                )

                if "timestamp" in combined_df.columns:
                    # Attach last observed value + timestamp per dimension.
                    idx = combined_df.groupby(dim_cols, dropna=False)["timestamp"].idxmax()
                    last = combined_df.loc[idx, dim_cols + ["timestamp", "value"]].rename(
                        columns={"timestamp": "last_timestamp", "value": "last_value"}
                    )
                    out = stats.merge(last, on=dim_cols, how="left")
                else:
                    out = stats

                if used_label_sig and "_labels_sig" in out.columns:
                    out["labels"] = out["_labels_sig"].apply(json.loads)
                    out = out.drop(columns=["_labels_sig"], errors="ignore")

                # Sort/limit for compact mode.
                if sort_by and sort_by in out.columns:
                    out = out.sort_values(sort_by, ascending=False)
                elif "max" in out.columns:
                    out = out.sort_values("max", ascending=False)

                if limit and len(out) > limit:
                    out = out.head(limit)

                return [TextContent(type="text", text=_df_to_json_records(out, compact=True))]

            # No dimension columns (edge case) -> just a global summary.
            summary = combined_df["value"].agg(["count", "mean", "min", "max"]).to_frame().T
            return [TextContent(type="text", text=_df_to_json_records(summary, compact=True))]

    # Group By and Aggregation
    if group_by:
        # Handle special 'deployment' extraction from pod names
        if group_by == 'deployment' and 'deployment' not in combined_df.columns:
            if 'pod_name' in combined_df.columns:
                combined_df['deployment'] = combined_df['pod_name'].apply(_extract_deployment_from_pod)
            elif '_object_name' in combined_df.columns:
                combined_df['deployment'] = combined_df['_object_name'].apply(_extract_deployment_from_pod)
        
        if group_by in combined_df.columns:
            numeric_cols = combined_df.select_dtypes(include=[np.number]).columns.tolist()
            numeric_cols = [c for c in numeric_cols if not c.startswith('_')]
            
            if numeric_cols:
                grouped = combined_df.groupby(group_by)[numeric_cols].agg(agg_func).reset_index()
                # Sort by eval result column if present
                if len(numeric_cols) > 0:
                    eval_col = None
                    if eval_query and "=" in eval_query:
                        eval_col = eval_query.split("=")[0].strip()
                    sort_col = eval_col if eval_col and eval_col in grouped.columns else numeric_cols[-1]
                    grouped = grouped.sort_values(sort_col, ascending=False)
                
                if compact_mode and sort_by and sort_by in grouped.columns:
                    grouped = grouped.sort_values(sort_by, ascending=False)
                if compact_mode and limit and len(grouped) > limit:
                    grouped = grouped.head(limit)

                return [TextContent(type="text", text=_df_to_json_records(grouped, compact=compact_mode))]
            else:
                return [TextContent(type="text", text=f"Error: No numeric columns found for aggregation")]
        else:
            return [TextContent(type="text", text=f"Error: Column '{group_by}' not found. Available: {list(combined_df.columns)}")]
    
    # If no group_by but agg is specified, aggregate all rows
    if agg_func and agg_func != 'mean':  # 'mean' is default, so explicit agg requested
        numeric_cols = combined_df.select_dtypes(include=[np.number]).columns.tolist()
        numeric_cols = [c for c in numeric_cols if not c.startswith('_')]
        if numeric_cols:
            result = combined_df[numeric_cols].agg(agg_func).to_frame().T
            return [TextContent(type="text", text=_df_to_json_records(result, compact=compact_mode))]
             
    # Return data
    # If we pivoted, we have wide format. If not, long format.
    if 'timestamp' in combined_df.columns:
        combined_df = combined_df.sort_values('timestamp')
        combined_df['timestamp'] = combined_df['timestamp'].astype(str)
    
    # Drop internal columns for cleaner output
    output_df = combined_df.drop(columns=[c for c in combined_df.columns if c.startswith('_')], errors='ignore')

    if compact_mode and sort_by and sort_by in output_df.columns:
        output_df = output_df.sort_values(sort_by, ascending=False)
    if compact_mode and limit and len(output_df) > limit:
        output_df = output_df.head(limit)

    return [TextContent(type="text", text=_df_to_json_records(output_df, compact=compact_mode))]


async def _get_metric_anomalies(args: dict[str, Any]) -> list[TextContent]:
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    k8_object_name = args.get("k8_object_name", "")
    base_dir = args.get("base_dir", "")
    metric_name_filter = args.get("metric_name_filter")
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    raw_content = args.get("raw_content", True)
    
    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None
    
    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Metrics directory not found: {base_dir}")]
    
    # Parse kind and name
    try:
        kind, name = k8_object_name.split("/", 1)
    except ValueError:
        return [TextContent(type="text", text="Invalid k8_object_name format. Use '<kind>/<name>'")]
    
    # Find relevant files
    # Try multiple name patterns to handle naming variations
    # e.g., "product-catalog-service" -> try "product-catalog-service", "product-catalog"
    name_variants = [name]
    for suffix in ["-service", "_service", "-svc", "_svc"]:
        if name.endswith(suffix):
            name_variants.append(name[:-len(suffix)])
    
    files = []
    for variant in name_variants:
        prefix = f"{kind.lower()}_{variant}"
        files = list(base_path.glob(f"{prefix}*.tsv"))
        if files:
            break
    
    if not files:
        return [TextContent(type="text", text=f"No metric files found for {k8_object_name}")]
    
    results = {
        "object": k8_object_name,
        "metrics": []
    }
    
    for file_path in files:
        try:
            # Read TSV with pandas
            df = pd.read_csv(file_path, sep='\t')
            
            # Apply metric name filter
            if metric_name_filter:
                if 'metric_name' in df.columns:
                    df = df[df['metric_name'].str.contains(metric_name_filter, na=False)]
                
                if df.empty:
                    continue

            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            
            # Filter by time
            if start_time:
                df = df[df['timestamp'] >= _to_utc_timestamp(start_time)]
            if end_time:
                df = df[df['timestamp'] <= _to_utc_timestamp(end_time)]
            
            if df.empty:
                continue

            # Calculate stats and anomalies
            # Using simple Z-score on 'value' column
            if 'value' in df.columns:
                mean = df['value'].mean()
                std = df['value'].std()
                
                # If std is 0, no anomalies possible unless we define deviation from mean 0
                anomalies = []
                if std > 0:
                    threshold = mean + 2 * std
                    anomaly_df = df[df['value'] > threshold]
                    anomalies = anomaly_df.to_dict(orient='records')
            else:
                anomalies = []
            
            # Convert timestamp back to string for JSON serialization
            if 'timestamp' in df.columns:
                df['timestamp'] = df['timestamp'].astype(str)
                # Convert anomaly timestamps too
                for a in anomalies:
                    if 'timestamp' in a:
                        a['timestamp'] = str(a['timestamp'])

            metric_data = {
                "metric_name": df['metric_name'].iloc[0] if 'metric_name' in df.columns else "unknown",
                "file": file_path.name,
                "count": len(df),
                "anomaly_count": len(anomalies),
                "anomalies": anomalies,
            }
            
            if raw_content:
                metric_data["data"] = df.to_dict(orient='records')
                
            results["metrics"].append(metric_data)
            
        except Exception as e:
            results["metrics"].append({"file": file_path.name, "error": str(e)})
            
    return [TextContent(type="text", text=json.dumps(results, indent=2))]


def _parse_otel_event_body(body_str: str) -> dict[str, Any]:
    """Parse OTEL event Body JSON and extract K8s event fields.
    
    OTEL format wraps K8s events in a JSON structure like:
    {
        "object": {
            "involvedObject": {"kind": "Pod", "name": "...", "namespace": "..."},
            "reason": "Scheduled",
            "message": "...",
            "lastTimestamp": "...",
            "type": "Normal"
        },
        "type": "ADDED"
    }
    
    Returns flattened dict with standard event columns.
    """
    try:
        body = json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        return {}
    
    obj = body.get("object", {})
    involved = obj.get("involvedObject", {}) or obj.get("regarding", {})
    
    return {
        "object_kind": involved.get("kind", ""),
        "object_name": involved.get("name", ""),
        "namespace": involved.get("namespace", ""),
        "reason": obj.get("reason", ""),
        "message": obj.get("message", "") or obj.get("note", ""),
        "event_time": obj.get("lastTimestamp") or obj.get("firstTimestamp") or obj.get("eventTime"),
        "event_kind": obj.get("type", ""),  # Normal, Warning
        "watch_type": body.get("type", ""),  # ADDED, MODIFIED, DELETED
        "count": obj.get("count", 1),
        "source_component": (obj.get("source", {}) or {}).get("component", ""),
    }


def _convert_otel_events_to_flat(df: "pd.DataFrame") -> "pd.DataFrame":
    """Convert OTEL-format events DataFrame to flat format.
    
    Detects if DataFrame is in OTEL format (has 'Body' column) and converts it.
    """
    if 'Body' not in df.columns:
        return df
    
    # Parse Body JSON and flatten
    parsed_rows = []
    for idx, row in df.iterrows():
        parsed = _parse_otel_event_body(row.get('Body', ''))
        if parsed.get('object_name'):  # Only include rows with valid data
            # Keep original timestamp if available
            if 'Timestamp' in row and row['Timestamp']:
                parsed['log_timestamp'] = row['Timestamp']
            parsed_rows.append(parsed)
    
    if not parsed_rows:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(columns=[
            'object_kind', 'object_name', 'namespace', 'reason', 
            'message', 'event_time', 'event_kind', 'watch_type', 'count', 'source_component'
        ])
    
    return pd.DataFrame(parsed_rows)


async def _event_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze Kubernetes events with SQL-like filter → group_by → agg flow.
    
    Supports both flat format (with columns like object_name, reason, etc.)
    and OTEL format (with Body column containing nested JSON).
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    events_file = args.get("events_file", "")
    filters = args.get("filters", {})
    group_by = args.get("group_by")
    agg_type = args.get("agg", "count")
    sort_by = args.get("sort_by")
    limit = args.get("limit")
    offset = args.get("offset", 0)
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    
    # limit=0 means no limit (fetch all)
    if limit == 0:
        limit = None
    
    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None
    
    if not Path(events_file).exists():
        return [TextContent(type="text", text=f"Events file not found: {events_file}")]
    
    try:
        df = pd.read_csv(events_file, sep='\t')
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading events file: {e}")]
    
    # Convert OTEL format to flat format if needed
    if 'Body' in df.columns:
        df = _convert_otel_events_to_flat(df)
        if df.empty:
            return [TextContent(type="text", text=json.dumps({
                "total_count": 0,
                "offset": 0,
                "limit": limit if limit else "all",
                "returned_count": 0,
                "data": [],
                "note": "Events file is in OTEL format but no valid K8s events found"
            }, indent=2))]
    
    # Add deployment column (extracted from pod/replicaset names in object_name)
    if 'object_name' in df.columns and 'object_kind' in df.columns:
        def extract_deployment(row):
            obj_kind = row.get('object_kind', '')
            obj_name = str(row.get('object_name', ''))
            if obj_kind == 'Pod':
                # Pod: <deployment>-<rs-hash>-<pod-hash>
                return _extract_deployment_from_pod(obj_name)
            elif obj_kind == 'ReplicaSet':
                # ReplicaSet: <deployment>-<rs-hash>
                parts = obj_name.rsplit("-", 1)
                if len(parts) >= 2 and len(parts[-1]) >= 5:  # hash is typically 9-10 chars
                    return parts[0]
            return obj_name if obj_name else 'unknown'
        df['deployment'] = df.apply(extract_deployment, axis=1)
    
    # Apply filters
    if filters:
        for col, val in filters.items():
            if col in df.columns:
                df = df[df[col] == val]
            else:
                return [TextContent(type="text", text=f"Error: Filter column '{col}' not found. Available: {list(df.columns)}")]
    
    # Filter by time
    time_col = 'event_time' if 'event_time' in df.columns else 'timestamp'
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce', utc=True)
        if start_time:
            df = df[df[time_col] >= _to_utc_timestamp(start_time)]
        if end_time:
            df = df[df[time_col] <= _to_utc_timestamp(end_time)]
    
    # Group By with multiple aggregation types
    if group_by:
        # Normalize group_by to list
        group_cols = [group_by] if isinstance(group_by, str) else list(group_by)
        
        # Check all group columns exist
        for col in group_cols:
            if col not in df.columns:
                return [TextContent(type="text", text=f"Error: Group column '{col}' not found. Available: {list(df.columns)}")]
        
        # Perform aggregation based on type
        if agg_type == 'count':
            grouped = df.groupby(group_cols).size().reset_index(name='count')
            sort_col = sort_by if sort_by and sort_by in grouped.columns else 'count'
            grouped = grouped.sort_values(sort_col, ascending=False)
            
        elif agg_type == 'first':
            grouped = df.sort_values(time_col).groupby(group_cols).first().reset_index()
            
        elif agg_type == 'last':
            grouped = df.sort_values(time_col).groupby(group_cols).last().reset_index()
            
        elif agg_type == 'nunique':
            # Count unique values in each non-group column
            agg_dict = {col: 'nunique' for col in df.columns if col not in group_cols}
            grouped = df.groupby(group_cols).agg(agg_dict).reset_index()
            # Rename columns to indicate they are counts
            grouped.columns = [f"{col}_unique" if col not in group_cols else col for col in grouped.columns]
            
        elif agg_type == 'list':
            # List unique values (useful for seeing all reasons for a pod)
            agg_dict = {col: lambda x: list(x.unique())[:10] for col in ['reason', 'message', 'event_kind'] if col in df.columns}
            if agg_dict:
                grouped = df.groupby(group_cols).agg(agg_dict).reset_index()
            else:
                grouped = df.groupby(group_cols).size().reset_index(name='count')
        else:
            return [TextContent(type="text", text=f"Error: Unknown aggregation type '{agg_type}'. Use: count, first, last, nunique, list")]
        
        total_rows = len(grouped)
        
        # Apply offset and limit (pagination)
        if offset > 0:
            grouped = grouped.iloc[offset:]
        if limit:
            grouped = grouped.head(limit)
        
        # Convert timestamps to string for JSON
        for col in grouped.columns:
            if pd.api.types.is_datetime64_any_dtype(grouped[col]):
                grouped[col] = grouped[col].astype(str)
        
        # Include pagination metadata
        result = {
            "total_count": total_rows,
            "offset": offset,
            "limit": limit if limit else "all",
            "returned_count": len(grouped),
            "data": json.loads(grouped.to_json(orient='records'))
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    # No group_by - return filtered data
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by)
    elif time_col in df.columns:
        df = df.sort_values(time_col)
    
    total_rows = len(df)
    
    # Apply offset and limit (pagination)
    if offset > 0:
        df = df.iloc[offset:]
    if limit:
        df = df.head(limit)
    
    # Convert timestamps to string for JSON
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
    
    # Include pagination metadata
    result = {
        "total_count": total_rows,
        "offset": offset,
        "limit": limit if limit else "all",
        "returned_count": len(df),
        "data": json.loads(df.to_json(orient='records'))
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _log_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze application logs from OTEL log files with LOG PATTERN MINING.
    
    Supports:
    - Pattern analysis using logmine (default: enabled)
    - Time window filtering (start_time, end_time)
    - Entity filtering (k8_object in Kind/name format)
    - Service name filtering
    - Severity filtering (ERROR, WARNING, INFO, etc.)
    - Body text search
    - Pagination (offset, limit) for raw log mode
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]
    
    logs_file = args.get("logs_file", "")
    k8_object = args.get("k8_object")
    service_name = args.get("service_name")
    severity_filter = args.get("severity_filter")
    body_contains = args.get("body_contains")
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    
    # Pattern analysis parameters
    pattern_analysis = args.get("pattern_analysis", True)
    max_patterns = args.get("max_patterns", 50)
    similarity_threshold = args.get("similarity_threshold", 0.5)
    
    # Pagination parameters (for raw log mode)
    limit = args.get("limit", 100)
    offset = args.get("offset", 0)
    
    # limit=0 means no limit
    if limit == 0:
        limit = None
    
    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None
    
    if not Path(logs_file).exists():
        return [TextContent(type="text", text=f"Logs file not found: {logs_file}")]
    
    try:
        df = pd.read_csv(logs_file, sep='\t')
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading logs file: {e}")]
    
    if df.empty:
        return [TextContent(type="text", text=json.dumps({
            "total_count": 0,
            "patterns" if pattern_analysis else "data": []
        }, indent=2))]
    
    # Parse ResourceAttributes to extract k8s metadata
    def extract_k8s_metadata(resource_attrs_str):
        """Extract k8s metadata from ResourceAttributes string."""
        try:
            if pd.isna(resource_attrs_str) or not resource_attrs_str:
                return {}
            attrs_str = str(resource_attrs_str)
            attrs = eval(attrs_str)  # Safe here since it's our own data
            return {
                "deployment": attrs.get("k8s.deployment.name", ""),
                "pod": attrs.get("k8s.pod.name", ""),
                "namespace": attrs.get("k8s.namespace.name", ""),
                "node": attrs.get("k8s.node.name", ""),
                "service": attrs.get("service.name", ""),
            }
        except Exception:
            return {}
    
    # Extract k8s metadata if we need to filter by k8_object
    if k8_object or 'ResourceAttributes' in df.columns:
        k8s_metadata = df['ResourceAttributes'].apply(extract_k8s_metadata)
        df['_deployment'] = k8s_metadata.apply(lambda x: x.get('deployment', ''))
        df['_pod'] = k8s_metadata.apply(lambda x: x.get('pod', ''))
        df['_namespace'] = k8s_metadata.apply(lambda x: x.get('namespace', ''))
    
    # Filter by k8_object (Kind/name format)
    if k8_object:
        try:
            kind, name = k8_object.split("/", 1)
            kind_lower = kind.lower()
            
            name_variants = [name.lower()]
            for suffix in ["-service", "_service", "-svc", "_svc"]:
                if name.lower().endswith(suffix):
                    name_variants.append(name.lower()[:-len(suffix)])
            
            if kind_lower in ["deployment", "deploy"]:
                mask = df['_deployment'].str.lower().isin(name_variants)
            elif kind_lower == "pod":
                mask = df['_pod'].str.lower().str.contains('|'.join(name_variants), na=False, regex=True)
            elif kind_lower in ["service", "svc", "app"]:
                svc_mask = df['ServiceName'].str.lower().isin(name_variants) if 'ServiceName' in df.columns else pd.Series([False] * len(df))
                deploy_mask = df['_deployment'].str.lower().isin(name_variants)
                mask = svc_mask | deploy_mask
            else:
                svc_mask = df['ServiceName'].str.lower().isin(name_variants) if 'ServiceName' in df.columns else pd.Series([False] * len(df))
                deploy_mask = df['_deployment'].str.lower().isin(name_variants)
                mask = svc_mask | deploy_mask
            
            df = df[mask]
        except ValueError:
            return [TextContent(type="text", text=f"Invalid k8_object format: '{k8_object}'. Use 'Kind/name' format.")]
    
    # Filter by service_name
    if service_name and 'ServiceName' in df.columns:
        df = df[df['ServiceName'].str.lower() == service_name.lower()]
    
    # Filter by severity
    if severity_filter and 'SeverityText' in df.columns:
        severities = [s.strip().upper() for s in severity_filter.split(',')]
        df = df[df['SeverityText'].str.upper().isin(severities)]
    
    # Filter by body contains
    if body_contains and 'Body' in df.columns:
        df = df[df['Body'].str.contains(body_contains, case=False, na=False)]
    
    # Filter by time window
    time_col = 'Timestamp' if 'Timestamp' in df.columns else 'TimestampTime'
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce', utc=True)
        if start_time:
            df = df[df[time_col] >= _to_utc_timestamp(start_time)]
        if end_time:
            df = df[df[time_col] <= _to_utc_timestamp(end_time)]
    
    total_rows = len(df)
    
    if total_rows == 0:
        return [TextContent(type="text", text=json.dumps({
            "total_count": 0,
            "filters_applied": {
                "k8_object": k8_object,
                "service_name": service_name,
                "severity_filter": severity_filter,
                "body_contains": body_contains,
                "start_time": start_time_str,
                "end_time": end_time_str
            },
            "patterns" if pattern_analysis else "data": []
        }, indent=2))]
    
    # =========================================================================
    # PATTERN ANALYSIS MODE (using drain3)
    # =========================================================================
    if pattern_analysis:
        if TemplateMiner is None:
            return [TextContent(type="text", text="Error: drain3 is required for pattern analysis. Install with: pip install drain3")]
        
        # Configure drain3 with similarity threshold
        # sim_th controls how similar logs must be to group together (default 0.4)
        # Lower threshold = more distinct patterns, higher = more grouping
        config = TemplateMinerConfig()
        config.drain_sim_th = similarity_threshold
        config.drain_depth = 4
        config.drain_max_children = 100
        config.drain_max_clusters = max_patterns * 2  # Allow some buffer
        
        # Add common masking patterns for cleaner templates using MaskingInstruction
        if MaskingInstruction is not None:
            config.masking_instructions = [
                # UUIDs (e.g., 3668f213-3a05-42a5-add7-927432543d35)
                MaskingInstruction(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>"),
                # IP addresses (simple pattern)
                MaskingInstruction(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>"),
                # Hex numbers
                MaskingInstruction(r"0x[0-9a-fA-F]+", "<HEX>"),
            ]
        
        template_miner = TemplateMiner(config=config)
        
        # Build index mapping: cluster_id -> list of (df_index, log_body)
        cluster_to_logs: Dict[int, List[tuple]] = {}
        log_bodies = df['Body'].fillna('').astype(str).tolist()
        df_indices = df.index.tolist()
        
        # Process each log message
        for df_idx, body in zip(df_indices, log_bodies):
            if not body.strip():
                continue
            result = template_miner.add_log_message(body)
            cluster_id = result.get("cluster_id")
            if cluster_id is not None:
                if cluster_id not in cluster_to_logs:
                    cluster_to_logs[cluster_id] = []
                cluster_to_logs[cluster_id].append((df_idx, body))
        
        # Build pattern results from clusters
        patterns = []
        for cluster in template_miner.drain.clusters:
            cluster_id = cluster.cluster_id
            pattern_template = cluster.get_template()
            
            # Get logs belonging to this cluster
            cluster_logs = cluster_to_logs.get(cluster_id, [])
            if not cluster_logs:
                continue
            
            matching_indices = [log[0] for log in cluster_logs]
            count = len(matching_indices)
            
            # Get example log (first one in cluster)
            example_idx = matching_indices[0]
            example_row = df.loc[example_idx]
            example_log = {
                "body": str(example_row.get('Body', ''))[:500],  # Truncate long bodies
                "timestamp": str(example_row.get(time_col, '')) if time_col in df.columns else None,
                "service": str(example_row.get('ServiceName', '')) if 'ServiceName' in df.columns else None,
                "severity": str(example_row.get('SeverityText', '')) if 'SeverityText' in df.columns else None,
            }
            
            # Compute severity breakdown
            severity_breakdown = {}
            if 'SeverityText' in df.columns:
                matched_df = df.loc[matching_indices]
                severity_counts = matched_df['SeverityText'].value_counts().to_dict()
                severity_breakdown = {str(k): int(v) for k, v in severity_counts.items()}
            
            # Compute time range
            time_range = {}
            if time_col in df.columns:
                matched_df = df.loc[matching_indices]
                valid_times = matched_df[time_col].dropna()
                if len(valid_times) > 0:
                    time_range = {
                        "first": str(valid_times.min()),
                        "last": str(valid_times.max())
                    }
            
            # Compute service breakdown
            service_breakdown = {}
            if 'ServiceName' in df.columns:
                matched_df = df.loc[matching_indices]
                svc_counts = matched_df['ServiceName'].value_counts().to_dict()
                service_breakdown = {str(k): int(v) for k, v in svc_counts.items()}
            
            patterns.append({
                "pattern": pattern_template,
                "count": count,
                "percentage": round(100 * count / total_rows, 2),
                "severity_breakdown": severity_breakdown,
                "service_breakdown": service_breakdown,
                "time_range": time_range,
                "example": example_log
            })
        
        # Sort by count (most frequent first) and limit
        patterns.sort(key=lambda x: x['count'], reverse=True)
        patterns = patterns[:max_patterns]
        
        result = {
            "total_logs": total_rows,
            "pattern_count": len(patterns),
            "similarity_threshold": similarity_threshold,
            "filters_applied": {
                "k8_object": k8_object,
                "service_name": service_name,
                "severity_filter": severity_filter,
                "body_contains": body_contains,
                "start_time": start_time_str,
                "end_time": end_time_str
            },
            "patterns": patterns
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    # =========================================================================
    # RAW LOG MODE (original pagination behavior)
    # =========================================================================
    # Sort by timestamp (most recent first)
    if time_col in df.columns:
        df = df.sort_values(time_col, ascending=False)
    
    # Apply pagination
    if offset > 0:
        df = df.iloc[offset:]
    if limit:
        df = df.head(limit)
    
    # Select output columns
    output_cols = []
    for col in ['Timestamp', 'ServiceName', 'SeverityText', 'Body', 'TraceId', 'SpanId', '_deployment', '_pod', '_namespace']:
        if col in df.columns:
            output_cols.append(col)
    
    if output_cols:
        df_output = df[output_cols].copy()
    else:
        df_output = df.copy()
    
    # Convert timestamps to string for JSON
    for col in df_output.columns:
        if pd.api.types.is_datetime64_any_dtype(df_output[col]):
            df_output[col] = df_output[col].astype(str)
    
    # Rename internal columns
    col_rename = {'_deployment': 'deployment', '_pod': 'pod', '_namespace': 'namespace'}
    df_output = df_output.rename(columns={k: v for k, v in col_rename.items() if k in df_output.columns})
    
    result = {
        "total_count": total_rows,
        "offset": offset,
        "limit": limit if limit else "all",
        "returned_count": len(df_output),
        "filters_applied": {
            "k8_object": k8_object,
            "service_name": service_name,
            "severity_filter": severity_filter,
            "body_contains": body_contains,
            "start_time": start_time_str,
            "end_time": end_time_str
        },
        "data": json.loads(df_output.to_json(orient='records'))
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _compute_percentiles(latencies: List[float]) -> Dict[str, float]:
    """Compute p50, p90, p99 percentiles for a list of latencies."""
    if not latencies:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    return {
        "p50": round(sorted_lat[int(n * 0.50)] if n > 0 else 0, 2),
        "p90": round(sorted_lat[min(int(n * 0.90), n - 1)] if n > 0 else 0, 2),
        "p99": round(sorted_lat[min(int(n * 0.99), n - 1)] if n > 0 else 0, 2),
    }


def _format_latency(ms: float) -> str:
    """Format latency in human-readable form."""
    if ms < 1:
        return f"{ms:.2f}ms"
    elif ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        return f"{ms/60000:.1f}m"


def _format_rate(rate: float) -> str:
    """Format rate as X/s."""
    if rate < 1:
        return f"{rate:.2f}/s"
    else:
        return f"{rate:.0f}/s"


def _compute_delta(pre_val: float, post_val: float) -> float:
    """Compute percentage change from pre to post value."""
    if pre_val == 0:
        return float('inf') if post_val > 0 else 0.0
    return round((post_val - pre_val) / pre_val * 100, 1)


def _compute_window_summary_compact(
    spans: List[Dict[str, Any]], 
    window_start: datetime, 
    window_end: datetime
) -> Dict[str, Any]:
    """Compute compact summary statistics for a time window."""
    if not spans:
        return None
    
    trace_ids = set(s.get("trace_id") for s in spans if s.get("trace_id"))
    trace_count = len(trace_ids)
    span_count = len(spans)
    
    window_duration_sec = (window_end - window_start).total_seconds()
    traffic_rate = round(trace_count / window_duration_sec, 2) if window_duration_sec > 0 else 0
    
    error_count = sum(1 for s in spans if s.get("status_code") == "Error")
    error_rate_pct = round((error_count / span_count * 100), 2) if span_count > 0 else 0
    
    latencies = []
    for s in spans:
        try:
            dur = float(s.get("duration_ms", 0))
            latencies.append(dur)
        except (ValueError, TypeError):
            pass
    
    percentiles = _compute_percentiles(latencies)
    
    return {
        "trace_count": trace_count,
        "error_rate_pct": error_rate_pct,
        "latency_p99_ms": percentiles["p99"]
    }


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
    spans_by_trace: Dict[str, List[Dict[str, Any]]],
    target_service: str = None
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
                "spans": []  # All spans belonging to traces on this path
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
    window_duration_sec: float
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
        "window_duration_sec": window_duration_sec
    }


def _classify_severity(
    pre_stats: Dict[str, Any], 
    post_stats: Dict[str, Any],
    error_threshold: float,
    latency_threshold: float
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
            snake_key = ''.join(['_' + c.lower() if c.isupper() else c for c in key]).lstrip('_')
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
        return [TextContent(type="text", text=f"No traces found containing service: {service_name}" if service_name else "No valid trace paths found")]
    
    # Step 4: Compute stats for each path
    path_stats_list = []
    for path_key, path_group in path_groups.items():
        if pivot_time:
            stats = _compute_path_stats(
                path_group, pre_start, pre_end, post_start, post_end, window_duration_sec
            )
        else:
            # Single window mode - use post_start/end as the only window, pre is empty
            stats = _compute_path_stats(
                path_group, 
                post_start, post_start,  # Empty pre window
                post_start, post_end, 
                window_duration_sec
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
            "post": f"[pivot_time, pivot_time + {delta_time_str}]" if pivot_time else "All data"
        },
        "thresholds": {
            "error_rate_change_pct": error_threshold,
            "latency_change_pct": latency_threshold
        },
        "note": "Each path groups traces that follow the same service chain. Stats are computed from spans within those specific traces."
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
            "pre": {
                "trace_count": sum(len(pg["trace_ids"]) for pg in path_groups.values()),
                "span_count": total_pre["count"],
                "error_rate_pct": round(pre_err_pct, 1),
                "latency_p99_ms": _compute_percentiles(total_pre["latencies"])["p99"]
            } if total_pre["count"] > 0 else None,
            "post": {
                "trace_count": sum(len(pg["trace_ids"]) for pg in path_groups.values()),
                "span_count": total_post["count"],
                "error_rate_pct": round(post_err_pct, 1),
                "latency_p99_ms": _compute_percentiles(total_post["latencies"])["p99"]
            } if total_post["count"] > 0 else None
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
                
                hops.append({
                    "service": svc,
                    "traffic": f"{_format_rate(h_pre_rate)} → {_format_rate(h_post_rate)}",
                    "error_rate": f"{h_pre_err:.0f}% → {h_post_err:.0f}%",
                    "latency_p99": f"{_format_latency(h_pre_lat['p99'])} → {_format_latency(h_post_lat['p99'])}"
                })
            
            critical_path = {
                "path": path_key,
                "severity": severity,
                "hops": hops,
                "sample_errors": list(ps.get("error_messages", set()))[:3]
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
                    "reason": f"{max_err_rate:.0f}% error rate"
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
        "latency_threshold_pct": latency_threshold
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _resolve_alert_column(col: str, available_cols: list) -> str:
    """Resolve column shortcuts for alerts.
    
    Maps user-friendly names to actual flattened column names:
    - alertname → labels.alertname
    - severity → labels.severity
    - service_name → labels.service_name
    - namespace → labels.namespace
    """
    shortcuts = {
        'alertname': 'labels.alertname',
        'severity': 'labels.severity',
        'service_name': 'labels.service_name',
        'service': 'labels.service_name',
        'namespace': 'labels.namespace',
    }
    
    # Check if it's a shortcut
    if col in shortcuts:
        resolved = shortcuts[col]
        if resolved in available_cols:
            return resolved
    
    # Return as-is if it exists
    if col in available_cols:
        return col
    
    # Try with labels. prefix
    if f'labels.{col}' in available_cols:
        return f'labels.{col}'
    
    return col  # Return original, will fail later if invalid


async def _alert_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze alerts with SQL-like filter → group_by → agg flow."""
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    base_dir = args.get("base_dir", "")
    time_basis = args.get("time_basis", "snapshot")
    filters = args.get("filters", {})
    group_by = args.get("group_by")
    agg_type = args.get("agg", "count")
    sort_by = args.get("sort_by")
    limit = args.get("limit")
    offset = args.get("offset", 0)
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    
    # limit=0 means no limit (fetch all)
    if limit == 0:
        limit = None
    
    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    # Normalize start/end bounds to naive UTC datetimes for consistent comparison.
    # (Snapshot timestamps are parsed as UTC then made tz-naive.)
    start_bound = None
    end_bound = None
    if start_time:
        st = pd.Timestamp(start_time)
        if st.tzinfo is not None:
            st = st.tz_convert('UTC').tz_localize(None)
        start_bound = st.to_pydatetime()
    if end_time:
        et = pd.Timestamp(end_time)
        if et.tzinfo is not None:
            et = et.tz_convert('UTC').tz_localize(None)
        end_bound = et.to_pydatetime()
    
    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Alerts directory not found: {base_dir}")]
    
    # Auto-detect alerts/ subdirectory if base_path doesn't have JSON files directly
    alerts_subdir = base_path / "alerts"
    if alerts_subdir.is_dir() and not list(base_path.glob("*.json")):
        base_path = alerts_subdir
    
    # Load all alerts from JSON files
    all_alerts = []
    
    for json_file in sorted(base_path.glob("*.json")):
        try:
            data = read_json_file(json_file)
            
            file_ts = _extract_alert_snapshot_timestamp(json_file, data)
            
            # Handle nested structure: data.alerts or just alerts array
            if isinstance(data, dict):
                if 'data' in data and 'alerts' in data['data']:
                    alerts_list = data['data']['alerts']
                elif 'alerts' in data:
                    alerts_list = data['alerts']
                else:
                    alerts_list = [data]
            else:
                alerts_list = data if isinstance(data, list) else [data]
            
            # Add file timestamp to each alert for duration calculation (only if we have a valid timestamp)
            if file_ts:
                for alert in alerts_list:
                    alert['_file_timestamp'] = file_ts
            
            all_alerts.extend(alerts_list)
        except Exception:
            continue
            
    if not all_alerts:
        return [TextContent(type="text", text="[]")]

    # Normalize JSON to DataFrame (flattens nested labels/annotations)
    df = pd.json_normalize(all_alerts)
    
    # Compute duration_active (how long alert has been firing at the snapshot time)
    time_col = 'activeAt' if 'activeAt' in df.columns else 'startsAt'
    if time_col in df.columns and '_file_timestamp' in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors='coerce', utc=True)
        df['_file_timestamp'] = pd.to_datetime(df['_file_timestamp'], errors='coerce', utc=True)
        
        # Remove timezone info for consistent comparison
        if df[time_col].dt.tz is not None:
            df[time_col] = df[time_col].dt.tz_localize(None)
        if df['_file_timestamp'].dt.tz is not None:
            df['_file_timestamp'] = df['_file_timestamp'].dt.tz_localize(None)
        
        # Duration in minutes (snapshot_time - activeAt)
        df['duration_active_min'] = (df['_file_timestamp'] - df[time_col]).dt.total_seconds() / 60
        
        # Set negative durations (invalid) to NaN
        df.loc[df['duration_active_min'] < 0, 'duration_active_min'] = pd.NA
        df['duration_active_min'] = df['duration_active_min'].round(1)
        
        # Human-readable duration
        def format_duration(minutes):
            if pd.isna(minutes):
                return 'unknown'
            if minutes < 1:
                return '<1m'
            elif minutes < 60:
                return f'{int(minutes)}m'
            elif minutes < 1440:
                return f'{int(minutes // 60)}h {int(minutes % 60)}m'
            else:
                return f'{int(minutes // 1440)}d {int((minutes % 1440) // 60)}h'
        
        df['duration_active'] = df['duration_active_min'].apply(format_duration)

    # Expose snapshot timestamp as a stable output column (keep internal _file_timestamp for computations)
    if '_file_timestamp' in df.columns and 'snapshot_timestamp' not in df.columns:
        df['snapshot_timestamp'] = df['_file_timestamp']
    
    # Convert value to numeric
    if 'value' in df.columns:
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
    
    # Apply filters (with shortcut resolution)
    if filters:
        for col, val in filters.items():
            resolved_col = _resolve_alert_column(col, list(df.columns))
            if resolved_col in df.columns:
                df = df[df[resolved_col] == val]
            else:
                return [TextContent(type="text", text=f"Error: Filter column '{col}' not found. Available: {list(df.columns)}")]
    
    # Filter by time window (defaults to observation/snapshot time)
    basis_col = time_col
    if time_basis != "activeAt" and '_file_timestamp' in df.columns:
        basis_col = '_file_timestamp'

    if basis_col in df.columns:
        if start_time:
            start_ts = pd.Timestamp(start_time)
            if start_ts.tzinfo is not None:
                start_ts = start_ts.tz_convert('UTC').tz_localize(None)
            df = df[df[basis_col] >= start_ts]
        if end_time:
            end_ts = pd.Timestamp(end_time)
            if end_ts.tzinfo is not None:
                end_ts = end_ts.tz_convert('UTC').tz_localize(None)
            df = df[df[basis_col] <= end_ts]
    
    # Group By with multiple aggregation types
    if group_by:
        # Normalize group_by to list and resolve shortcuts
        group_cols_input = [group_by] if isinstance(group_by, str) else list(group_by)
        group_cols = [_resolve_alert_column(c, list(df.columns)) for c in group_cols_input]
        
        # Check all group columns exist
        for col in group_cols:
            if col not in df.columns:
                return [TextContent(type="text", text=f"Error: Group column '{col}' not found. Available: {list(df.columns)}")]
        
        # Perform aggregation
        if agg_type == 'count':
            grouped = df.groupby(group_cols).size().reset_index(name='count')
            sort_col = sort_by if sort_by and sort_by in grouped.columns else 'count'
            grouped = grouped.sort_values(sort_col, ascending=False)
            
        elif agg_type == 'first':
            sort_time_col = basis_col if basis_col in df.columns else time_col
            if sort_time_col in df.columns:
                grouped = df.sort_values(sort_time_col).groupby(group_cols).first().reset_index()
            else:
                grouped = df.groupby(group_cols).first().reset_index()
            
        elif agg_type == 'last':
            sort_time_col = basis_col if basis_col in df.columns else time_col
            if sort_time_col in df.columns:
                grouped = df.sort_values(sort_time_col).groupby(group_cols).last().reset_index()
            else:
                grouped = df.groupby(group_cols).last().reset_index()
            
        elif agg_type in ('sum', 'mean', 'max', 'min'):
            # Numeric aggregations on value and duration columns
            numeric_cols = ['value', 'duration_active_min']
            numeric_cols = [c for c in numeric_cols if c in df.columns]
            
            if numeric_cols:
                grouped = df.groupby(group_cols)[numeric_cols].agg(agg_type).reset_index()
                if sort_by and sort_by in grouped.columns:
                    grouped = grouped.sort_values(sort_by, ascending=False)
                elif 'value' in grouped.columns:
                    grouped = grouped.sort_values('value', ascending=False)
            else:
                return [TextContent(type="text", text=f"Error: No numeric columns for {agg_type} aggregation")]
        else:
            return [TextContent(type="text", text=f"Error: Unknown aggregation '{agg_type}'. Use: count, first, last, sum, mean, max, min")]
        
        total_rows = len(grouped)
        
        # Apply offset and limit (pagination)
        if offset > 0:
            grouped = grouped.iloc[offset:]
        if limit:
            grouped = grouped.head(limit)
        
        # Clean up internal columns and convert timestamps
        grouped = grouped.drop(columns=[c for c in grouped.columns if c.startswith('_')], errors='ignore')
        for col in grouped.columns:
            if pd.api.types.is_datetime64_any_dtype(grouped[col]):
                grouped[col] = grouped[col].astype(str)
        
        # Include pagination metadata
        result = {
            "total_count": total_rows,
            "offset": offset,
            "limit": limit if limit else "all",
            "returned_count": len(grouped),
            "data": json.loads(grouped.to_json(orient='records'))
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    # No group_by - return filtered data
    if sort_by:
        resolved_sort = _resolve_alert_column(sort_by, list(df.columns))
        if resolved_sort in df.columns:
            ascending = not (sort_by in ['duration_active_min', 'value', 'count'])  # Desc for these
            df = df.sort_values(resolved_sort, ascending=ascending)
    else:
        sort_time_col = basis_col if basis_col in df.columns else time_col
        if sort_time_col in df.columns:
            df = df.sort_values(sort_time_col)
    
    total_rows = len(df)
    
    # Apply offset and limit (pagination)
    if offset > 0:
        df = df.iloc[offset:]
    if limit:
        df = df.head(limit)
    
    # Clean up and convert timestamps
    df = df.drop(columns=[c for c in df.columns if c.startswith('_')], errors='ignore')
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
    
    # Include pagination metadata
    result = {
        "total_count": total_rows,
        "offset": offset,
        "limit": limit if limit else "all",
        "returned_count": len(df),
        "data": json.loads(df.to_json(orient='records'))
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# =============================================================================
# Alert Summary
# =============================================================================

async def _alert_summary(args: dict[str, Any]) -> list[TextContent]:
    """Provide a high-level summary of all alerts.
    
    For each unique alert type (alertname + entity + severity), calculates:
    - first_seen: earliest observation time in this dataset (snapshot time) while firing
    - last_seen: latest observation time in this dataset (snapshot time) while firing
    - duration_min: difference between last_seen and first_seen (observed incident window)
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]
    
    base_dir = args.get("base_dir", "")
    time_basis = args.get("time_basis", "snapshot")
    state_filter = args.get("state_filter")
    min_duration_min = args.get("min_duration_min")
    limit = args.get("limit", 50)
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    # Normalize start/end bounds to naive UTC datetimes for consistent comparison.
    # (Snapshot timestamps are parsed as UTC then made tz-naive.)
    start_bound = None
    end_bound = None
    if start_time:
        st = pd.Timestamp(start_time)
        if st.tzinfo is not None:
            st = st.tz_convert('UTC').tz_localize(None)
        start_bound = st.to_pydatetime()
    if end_time:
        et = pd.Timestamp(end_time)
        if et.tzinfo is not None:
            et = et.tz_convert('UTC').tz_localize(None)
        end_bound = et.to_pydatetime()
    
    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Alerts directory not found: {base_dir}")]
    
    # Auto-detect alerts/ subdirectory
    alerts_subdir = base_path / "alerts"
    if alerts_subdir.is_dir() and not list(base_path.glob("*.json")):
        base_path = alerts_subdir
    
    # Load all alerts from JSON files
    all_alerts = []
    
    for json_file in sorted(base_path.glob("*.json")):
        try:
            data = read_json_file(json_file)

            snapshot_ts = _extract_alert_snapshot_timestamp(json_file, data)
            snapshot_dt = None
            if snapshot_ts:
                try:
                    snapshot_dt = pd.to_datetime(snapshot_ts, utc=True).tz_localize(None).to_pydatetime()
                except Exception:
                    snapshot_dt = None

            # If we're doing snapshot-based filtering, filter at the file level.
            if time_basis != "activeAt" and snapshot_dt and (start_bound or end_bound):
                start_ok = True
                end_ok = True
                if start_bound:
                    start_ok = snapshot_dt >= start_bound
                if end_bound:
                    end_ok = snapshot_dt <= end_bound
                if not (start_ok and end_ok):
                    continue
            
            # Handle nested structure
            if isinstance(data, dict):
                if 'data' in data and 'alerts' in data['data']:
                    alerts_list = data['data']['alerts']
                elif 'alerts' in data:
                    alerts_list = data['alerts']
                else:
                    alerts_list = [data]
            else:
                alerts_list = data if isinstance(data, list) else [data]

            # Stamp each alert with the snapshot timestamp for observation-based summaries.
            if snapshot_ts:
                for alert in alerts_list:
                    if isinstance(alert, dict):
                        alert['_snapshot_timestamp'] = snapshot_ts
            
            all_alerts.extend(alerts_list)
                
        except Exception:
            pass
    
    if not all_alerts:
        return [TextContent(type="text", text="[]")]
    
    # Build summary by grouping alerts
    # Key: (alertname, entity, severity) -> {active_at_times, occurrences, states_seen, ...}
    alert_summaries: dict[tuple, dict] = {}
    
    for alert in all_alerts:
        labels = alert.get('labels', {})
        alertname = labels.get('alertname', alert.get('alertname', 'Unknown'))
        
        # Determine entity (service, pod, deployment, etc.)
        entity = (
            labels.get('service_name') or 
            labels.get('service') or 
            labels.get('pod') or 
            labels.get('deployment') or 
            labels.get('instance') or 
            labels.get('job') or
            labels.get('namespace', 'cluster-wide')
        )
        
        severity = labels.get('severity', 'unknown')
        namespace = labels.get('namespace', 'unknown')
        state = alert.get('state', 'unknown')
        
        # Parse activeAt timestamp (when alert first became active) - useful metadata.
        active_at = None
        if 'activeAt' in alert:
            try:
                ts = pd.to_datetime(alert['activeAt'])
                active_at = ts.tz_localize(None) if ts.tzinfo is None else ts.tz_convert(None)
                active_at = active_at.to_pydatetime()
            except Exception:
                pass

        # Parse observation/snapshot time (when this alert was observed in the dump)
        snapshot_at = None
        if '_snapshot_timestamp' in alert:
            try:
                ts = pd.to_datetime(alert['_snapshot_timestamp'], utc=True)
                snapshot_at = ts.tz_localize(None).to_pydatetime()
            except Exception:
                snapshot_at = None
        
        key = (alertname, entity, severity)
        
        if key not in alert_summaries:
            alert_summaries[key] = {
                'alertname': alertname,
                'entity': entity,
                'severity': severity,
                'namespace': namespace,
                'times': set(),  # snapshot times by default (or activeAt if time_basis='activeAt')
                'occurrences': 0,
                'states_seen': set(),
                'latest_state': state,
                'latest_time': None,
            }
        
        summary = alert_summaries[key]
        summary['occurrences'] += 1
        summary['states_seen'].add(state)

        # Track latest state based on the chosen time basis when possible.
        time_for_latest = snapshot_at if time_basis != "activeAt" else active_at
        if time_for_latest is not None:
            if summary['latest_time'] is None or time_for_latest >= summary['latest_time']:
                summary['latest_time'] = time_for_latest
                summary['latest_state'] = state
        else:
            # Fallback: keep updating to get the latest state in iteration order.
            summary['latest_state'] = state
        
        # Track time axis for alerts that are actively firing
        if state == 'firing':
            t = active_at if time_basis == "activeAt" else snapshot_at
            if t is not None:
                if start_bound and t < start_bound:
                    pass
                elif end_bound and t > end_bound:
                    pass
                else:
                    summary['times'].add(t)
    
    # Convert to list with calculated durations
    results = []
    for key, summary in alert_summaries.items():
        active_times = sorted(summary['times'])
        
        if active_times:
            first_seen = active_times[0]
            last_seen = active_times[-1]
            # Duration = observed time span within this dataset/window
            duration_min = (last_seen - first_seen).total_seconds() / 60
            duration_min = round(duration_min, 1)
        else:
            first_seen = None
            last_seen = None
            duration_min = None
        
        # Determine the effective state (prefer 'firing' if seen)
        state = summary['latest_state']
        if 'firing' in summary['states_seen']:
            state = 'firing'
        
        results.append({
            'alertname': summary['alertname'],
            'entity': summary['entity'],
            'namespace': summary['namespace'],
            'severity': summary['severity'],
            'state': state,
            'first_seen': str(first_seen) if first_seen else None,
            'last_seen': str(last_seen) if last_seen else None,
            'duration_min': duration_min,
            'occurrences': summary['occurrences']
        })
    
    # Apply filters
    if state_filter:
        results = [r for r in results if r['state'] == state_filter]

    # If a time window was provided, only keep alerts observed firing in that window.
    if start_bound or end_bound:
        results = [r for r in results if r['first_seen'] is not None]
    
    if min_duration_min is not None:
        results = [r for r in results if r['duration_min'] is not None and r['duration_min'] >= min_duration_min]
    
    # Sort by duration (longest first), then by occurrences
    results.sort(key=lambda x: (-(x['duration_min'] or 0), -x['occurrences']))
    
    # Apply limit
    if limit:
        results = results[:limit]
    
    return [TextContent(type="text", text=json.dumps(results, indent=2))]


# =============================================================================
# K8s Spec Change Analysis
# =============================================================================

# Fields to ignore when computing spec diffs (these cause "churn" without meaningful changes)
_IGNORE_SPEC_FIELDS = {
    "resourceVersion",
    "managedFields",
    "generation",
    "uid",
    "selfLink",
    "creationTimestamp",
    "time",
    "lastTransitionTime",
    "lastUpdateTime",
    "lastProbeTime",
    "lastHeartbeatTime",
    "observedGeneration",
    "containerStatuses",
    "conditions",
    "podIP",
    "podIPs",
    "hostIP",
    "startTime",
    "status",  # Status is often ephemeral
}

# Annotations that are timestamp-related
_IGNORE_ANNOTATIONS = {
    "endpoints.kubernetes.io/last-change-trigger-time",
    "kubectl.kubernetes.io/last-applied-configuration",
    "deployment.kubernetes.io/revision",
}

_PRESERVE_TIMESTAMP_KEYS = {
    # Useful lifecycle evidence; do not drop just because it contains "timestamp".
    "deletiontimestamp",
}


def _clean_spec_for_diff(obj: Any, path: str = "") -> Any:
    """Recursively clean a spec object, removing fields that cause churn."""
    if isinstance(obj, dict):
        cleaned = {}
        for key, value in obj.items():
            # Skip explicitly ignored fields
            if key in _IGNORE_SPEC_FIELDS:
                continue
            
            # Skip timestamp-like keys
            key_lc = key.lower()
            # Avoid overly-broad substring matching ("timeoutSeconds" is meaningful).
            # Only drop keys that *look like timestamps* by name.
            if (
                key_lc not in _PRESERVE_TIMESTAMP_KEYS
                and (key_lc.endswith("timestamp") or key_lc.endswith("time") or key_lc.endswith("date"))
            ):
                continue
            
            # Handle annotations specially
            if key == "annotations" and isinstance(value, dict):
                filtered_annotations = {
                    k: v for k, v in value.items() 
                    if k not in _IGNORE_ANNOTATIONS and "time" not in k.lower()
                }
                if filtered_annotations:
                    cleaned[key] = filtered_annotations
                continue
            
            # Recurse
            cleaned_value = _clean_spec_for_diff(value, f"{path}.{key}")
            if cleaned_value is not None:
                cleaned[key] = cleaned_value
        
        return cleaned if cleaned else None
    
    elif isinstance(obj, list):
        cleaned_list = []
        for item in obj:
            cleaned_item = _clean_spec_for_diff(item, path)
            if cleaned_item is not None:
                cleaned_list.append(cleaned_item)
        return cleaned_list if cleaned_list else None
    
    else:
        return obj


def _parse_k8s_body_json(raw: Any) -> dict[str, Any] | None:
    """Parse a Kubernetes object JSON from TSV/OTEL strings.

    Handles:
    - Raw OTEL TSV "Body" where the JSON object is stored as a quoted string with doubled quotes
    - Already-decoded JSON strings (double-encoded)
    - Processed TSV where body is a JSON object string
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None

    s = raw.strip()
    if not s:
        return None

    # Raw TSV may store JSON as quoted string with doubled quotes.
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    s = s.replace('""', '"')

    try:
        obj: Any = json.loads(s)
    except Exception:
        return None

    # Some inputs are double-encoded (JSON string containing JSON object).
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return None

    return obj if isinstance(obj, dict) else None


def _normalize_for_diff(obj: Any) -> Any:
    """Normalize spec shapes to make diffs stable and less noisy.

    Primary goal: avoid position-based diffs for "name-keyed" lists (containers/env/volumes/...).
    Converts lists of dicts that all have a unique string `name` into dicts keyed by that name.
    """
    if isinstance(obj, dict):
        return {k: _normalize_for_diff(v) for k, v in obj.items()}

    if isinstance(obj, list):
        if obj and all(isinstance(it, dict) and isinstance(it.get("name"), str) for it in obj):
            out: dict[str, Any] = {}
            for it in obj:
                name = it.get("name")
                if not isinstance(name, str) or not name:
                    # Shouldn't happen due to the all(...) guard, but be defensive.
                    return [_normalize_for_diff(x) for x in obj]
                if name in out:
                    # Duplicate keys -> keep list form rather than losing data.
                    return [_normalize_for_diff(x) for x in obj]

                # Drop the redundant "name" key so paths become containers.<name>.image, etc.
                item_no_name = {k: v for k, v in it.items() if k != "name"}
                out[name] = _normalize_for_diff(item_no_name)
            return out

        return [_normalize_for_diff(x) for x in obj]

    return obj


def _effective_update_timestamp(obj: dict[str, Any]) -> "pd.Timestamp | None":
    """Extract an 'effective update time' from a Kubernetes object.

    This is used to answer: "did this change happen in the window?" even when the
    OTEL k8sobjects snapshot observes the updated object later.

    Heuristics (UTC):
    - max(metadata.managedFields[].time)
    - max(spec.template.metadata.annotations.kubectl.kubernetes.io/restartedAt)
    """
    if pd is None:
        return None

    if not isinstance(obj, dict):
        return None

    candidates: list["pd.Timestamp"] = []

    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        managed = meta.get("managedFields") or []
        if isinstance(managed, list):
            for entry in managed:
                if not isinstance(entry, dict):
                    continue
                t = entry.get("time")
                if not t:
                    continue
                ts = pd.to_datetime(t, errors="coerce", utc=True)
                if pd.notna(ts):
                    candidates.append(ts)

    # kubectl rollout restart often annotates this timestamp on the pod template
    restarted_at = None
    try:
        restarted_at = (
            (obj.get("spec") or {})
            .get("template", {})
            .get("metadata", {})
            .get("annotations", {})
            .get("kubectl.kubernetes.io/restartedAt")
        )
    except Exception:
        restarted_at = None

    if restarted_at:
        ts = pd.to_datetime(restarted_at, errors="coerce", utc=True)
        if pd.notna(ts):
            candidates.append(ts)

    if not candidates:
        return None

    return max(candidates)


def _compute_diff(old: Any, new: Any, path: str = "") -> list[dict]:
    """Compute differences between two objects recursively.
    
    Returns a list of changes: {"path": "...", "type": "added|removed|changed", "old": ..., "new": ...}
    No truncation - full values are returned.
    """
    changes = []
    
    if type(old) != type(new):
        changes.append({"path": path or "root", "type": "changed", "old": old, "new": new})
        return changes
    
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        # Deterministic ordering so pagination + diffs are stable across runs.
        for key in sorted(all_keys, key=lambda k: str(k)):
            sub_path = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({"path": sub_path, "type": "added", "new": new[key]})
            elif key not in new:
                changes.append({"path": sub_path, "type": "removed", "old": old[key]})
            else:
                changes.extend(_compute_diff(old[key], new[key], sub_path))
    
    elif isinstance(old, list) and isinstance(new, list):
        # For lists, do a simple length/content comparison
        if len(old) != len(new):
            changes.append({"path": path or "root", "type": "changed", "old": old, "new": new})
        else:
            for i, (o, n) in enumerate(zip(old, new)):
                changes.extend(_compute_diff(o, n, f"{path}[{i}]"))
    
    elif old != new:
        changes.append({"path": path or "root", "type": "changed", "old": old, "new": new})
    
    return changes


async def _k8s_spec_change_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze K8s object spec changes over time.
    
    Groups by entity (kind/name), computes diffs between consecutive observations,
    filters out timestamp-related churn, and reports meaningful spec changes with duration.
    
    Supports two input formats:
    1) Processed format: columns timestamp, object_kind, object_name, body
    2) Raw OTEL format: columns Timestamp/TimestampTime, Body (JSON with kind/metadata.name)
    """
    def _json_error(message: str) -> list[TextContent]:
        """Return a structured JSON error so callers can reliably parse the response."""
        payload = {
            "error": message,
            "reference_spec_file": args.get("k8s_objects_file", ""),
            "total_change_events": 0,
            "returned_change_events": 0,
            "total_change_item_total": 0,
            "returned_change_item_total": 0,
            "total_entities": 0,
            "returned_count": 0,
            "offset": args.get("offset", 0),
            "limit": args.get("limit"),
            "entities_with_changes": [],
        }
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    if pd is None:
        return _json_error("pandas is required for this tool")
    
    k8s_objects_file = args.get("k8s_objects_file", "")
    k8_object_name = args.get("k8_object_name")  # Format: Kind/name
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    limit = args.get("limit")
    offset = args.get("offset", 0)
    include_no_change = args.get("include_no_change", False)
    max_changes_per_diff = args.get("max_changes_per_diff")
    include_reference_spec = args.get("include_reference_spec", True)
    include_flat_change_items = args.get("include_flat_change_items", True)
    sort_by = args.get("sort_by", "entity")  # entity|change_count
    time_basis_arg = args.get("time_basis")  # observation|effective_update

    # Lifecycle inference controls.
    #
    # Raw OTEL k8sobjectsreceiver output is not a true lifecycle stream; default to "none" there.
    lifecycle_inference_arg = args.get("lifecycle_inference")  # none|window
    lifecycle_scope_arg = args.get("lifecycle_scope")  # global|per_kind
    removal_grace_period_sec_arg = args.get("removal_grace_period_sec")
    removal_min_cycles_arg = args.get("removal_min_cycles")
    
    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None
    
    if not Path(k8s_objects_file).exists():
        return _json_error(f"K8s objects file not found: {k8s_objects_file}")
    
    try:
        df = pd.read_csv(k8s_objects_file, sep='\t')
    except Exception as e:
        return _json_error(f"Error reading k8s objects file: {e}")

    # -------------------------------------------------------------------------
    # Detect input format and normalize columns
    # -------------------------------------------------------------------------
    # 1) Processed format (expected): timestamp, object_kind, object_name, body
    # 2) Raw OTEL format (ITBenchSnapshots): Timestamp/TimestampTime, Body, ...
    #    For raw format, extract kind/name from JSON in Body column.
    # -------------------------------------------------------------------------
    cols = set(df.columns)
    is_raw_otel = False

    if "object_kind" not in cols or "object_name" not in cols:
        # Try to detect and handle raw OTEL format
        body_col = "Body" if "Body" in cols else ("body" if "body" in cols else None)
        if body_col is None:
            return _json_error(
                "Unsupported k8s objects format: missing object_kind/object_name columns and no Body column found"
            )

        # Find timestamp source column
        if "TimestampTime" in cols:
            ts_src = "TimestampTime"
        elif "Timestamp" in cols:
            ts_src = "Timestamp"
        elif "timestamp" in cols:
            ts_src = "timestamp"
        else:
            return _json_error(
                "Unsupported k8s objects format: no timestamp column (TimestampTime/Timestamp/timestamp)"
            )

        def _extract_kind_ns_name(raw: Any) -> tuple[str, str, str]:
            """Extract kind/namespace/name from a JSON Body string."""
            obj = _parse_k8s_body_json(raw)
            if not isinstance(obj, dict):
                return ("", "", "")
            kind = obj.get("kind", "") or ""
            meta = obj.get("metadata") or {}
            name = meta.get("name", "") or ""
            namespace = meta.get("namespace", "") or ""
            return (kind, namespace, name)

        extracted = df[body_col].apply(lambda x: pd.Series(_extract_kind_ns_name(x)))
        extracted.columns = ["object_kind", "object_namespace", "object_name"]
        df["object_kind"] = extracted["object_kind"]
        df["object_namespace"] = extracted["object_namespace"]
        df["object_name"] = extracted["object_name"]
        df["body"] = df[body_col].astype(str)
        df["timestamp"] = pd.to_datetime(df[ts_src], errors="coerce", utc=True)

        # Drop rows where extraction failed
        df = df[
            (df["object_kind"].astype(str) != "")
            & (df["object_name"].astype(str) != "")
        ]
        is_raw_otel = True
    else:
        # Processed format - ensure required columns exist
        if "timestamp" not in cols:
            return _json_error("Unsupported k8s objects format: missing 'timestamp' column")
        if "body" not in cols:
            if "Body" in cols:
                df["body"] = df["Body"].astype(str)
            else:
                return _json_error("Unsupported k8s objects format: missing 'body' column")

    # Normalize columns
    df["object_kind"] = df["object_kind"].fillna("").astype(str)
    if "object_namespace" not in df.columns:
        df["object_namespace"] = ""
    df["object_namespace"] = df["object_namespace"].fillna("").astype(str)
    df["object_name"] = df["object_name"].fillna("").astype(str)
    # Prefer Kind/namespace/name for namespaced resources; Kind/name for cluster-scoped.
    df["entity_id"] = df["object_kind"] + "/" + df["object_name"]
    _ns_mask = df["object_namespace"].astype(str) != ""
    df.loc[_ns_mask, "entity_id"] = (
        df.loc[_ns_mask, "object_kind"]
        + "/"
        + df.loc[_ns_mask, "object_namespace"]
        + "/"
        + df.loc[_ns_mask, "object_name"]
    )
    
    # Filter by specific object if provided
    if k8_object_name:
        # Support both exact match and case-insensitive partial match
        mask = (df['entity_id'].str.lower() == k8_object_name.lower())
        if not mask.any():
            # Try partial match
            mask = df['entity_id'].str.lower().str.contains(k8_object_name.lower(), na=False)
        df = df[mask]
        if df.empty:
            return _json_error(f"No objects matching '{k8_object_name}' found")
    
    # Parse timestamp (only for processed format; raw format already normalized above)
    if not is_raw_otel:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    
    # Filter by time range
    #
    # NOTE: If time_basis == "effective_update", we intentionally do NOT filter
    # the raw dataframe by observation time, because the updated object may be
    # observed later than its effective update time (managedFields/restartedAt).
    if time_basis_arg != "effective_update":
        if start_time:
            df = df[df['timestamp'] >= _to_utc_timestamp(start_time)]
        if end_time:
            df = df[df['timestamp'] <= _to_utc_timestamp(end_time)]
    
    if df.empty:
        return _json_error("No data after applying time filters")
    
    # Sort by entity and timestamp
    df = df.sort_values(['entity_id', 'timestamp'])

    # Resolve time basis defaults now that we know the input format.
    # - raw OTEL: default to effective_update for "did this change happen in window?" semantics
    # - processed: keep existing behavior unless overridden
    time_basis = time_basis_arg
    if time_basis is None:
        time_basis = "effective_update" if is_raw_otel else "observation"
    if time_basis not in {"observation", "effective_update"}:
        return _json_error(f"Unsupported time_basis: {time_basis}. Expected 'observation' or 'effective_update'")

    # Resolve lifecycle inference defaults now that we know the input format.
    lifecycle_inference = lifecycle_inference_arg
    lifecycle_scope = lifecycle_scope_arg
    if lifecycle_inference is None:
        lifecycle_inference = "none" if is_raw_otel else "window"
    if lifecycle_scope is None:
        lifecycle_scope = "per_kind" if is_raw_otel else "global"

    # Hysteresis defaults:
    # - Processed format keeps historical behavior (no grace/cycle gating by default).
    # - Raw OTEL: if lifecycle inference is enabled, require a gap and multiple subsequent cycles.
    if removal_grace_period_sec_arg is None:
        removal_grace_period_sec = 300 if (is_raw_otel and lifecycle_inference != "none") else 0
    else:
        removal_grace_period_sec = int(removal_grace_period_sec_arg)
    if removal_min_cycles_arg is None:
        removal_min_cycles = 2 if (is_raw_otel and lifecycle_inference != "none") else 0
    else:
        removal_min_cycles = int(removal_min_cycles_arg)
    
    # Global bounds within the filtered dataset. Used for lifecycle inference.
    #
    # IMPORTANT: lifecycle inference is about *observation presence within this window*.
    # - "added" means: first observed after the window start (as approximated by global_min_ts)
    # - "removed" means: last observed before the window end (as approximated by global_max_ts)
    # This is NOT a claim of permanent creation/deletion in the cluster; it's "not observed before/after"
    # given the data sampling in the TSV for this window.
    global_min_ts = df["timestamp"].min()
    global_max_ts = df["timestamp"].max()

    # Unique observation timestamps to approximate "collection cycles".
    all_unique_ts = sorted(df["timestamp"].dropna().unique())

    kind_min_ts: dict[str, Any] = {}
    kind_max_ts: dict[str, Any] = {}
    kind_unique_ts: dict[str, list[Any]] = {}
    if lifecycle_inference != "none" and lifecycle_scope == "per_kind":
        try:
            kind_min_ts = df.groupby("object_kind")["timestamp"].min().to_dict()
            kind_max_ts = df.groupby("object_kind")["timestamp"].max().to_dict()
            kind_unique_ts = {
                str(k): sorted(v.dropna().unique())
                for k, v in df.groupby("object_kind")["timestamp"]
            }
        except Exception:
            # If anything goes wrong, fall back to global bounds.
            kind_min_ts = {}
            kind_max_ts = {}
            kind_unique_ts = {}
    
    # Process each entity
    results = []
    entities = df['entity_id'].unique()
    total_entities_observed = len(entities)
    
    def _apply_change_limit(diff: list[dict]) -> tuple[list[dict], bool, int]:
        """Optionally truncate a diff to max_changes_per_diff items."""
        total_items = len(diff)
        if isinstance(max_changes_per_diff, int) and max_changes_per_diff > 0 and total_items > max_changes_per_diff:
            return (diff[:max_changes_per_diff], True, total_items)
        return (diff, False, total_items)
    
    for entity_id in entities:
        entity_df = df[df['entity_id'] == entity_id].copy()
        
        if len(entity_df) == 0:
            continue
        
        first_ts = entity_df['timestamp'].min()
        last_ts = entity_df['timestamp'].max()
        observation_count = len(entity_df)
        
        # Determine lifecycle inference bounds.
        entity_kind = str(entity_df["object_kind"].iloc[0]) if "object_kind" in entity_df.columns else ""
        scope_min_ts = kind_min_ts.get(entity_kind, global_min_ts) if lifecycle_scope == "per_kind" else global_min_ts
        scope_max_ts = kind_max_ts.get(entity_kind, global_max_ts) if lifecycle_scope == "per_kind" else global_max_ts
        scope_ts_list = kind_unique_ts.get(entity_kind, all_unique_ts) if lifecycle_scope == "per_kind" else all_unique_ts

        inferred_added = False
        inferred_removed = False
        if lifecycle_inference != "none":
            inferred_added = (
                pd.notna(first_ts)
                and pd.notna(scope_min_ts)
                and first_ts > scope_min_ts
            )

            if pd.notna(last_ts) and pd.notna(scope_max_ts) and last_ts < scope_max_ts:
                gap_sec = float((scope_max_ts - last_ts).total_seconds())
                post_cycles = sum(1 for t in scope_ts_list if t > last_ts)
                inferred_removed = (
                    gap_sec >= float(removal_grace_period_sec)
                    and post_cycles >= int(removal_min_cycles)
                )
        
        # Parse and clean specs
        specs = []
        for idx, row in entity_df.iterrows():
            try:
                body_obj = _parse_k8s_body_json(row.get("body"))
                if not body_obj:
                    continue

                meta = body_obj.get("metadata") or {}
                cleaned = _clean_spec_for_diff(body_obj)
                cleaned = _normalize_for_diff(cleaned)
                effective_ts = _effective_update_timestamp(body_obj)
                specs.append({
                    # Observation timestamp: when this object snapshot was recorded.
                    'timestamp': row['timestamp'],
                    # Effective update timestamp: best-effort "when the object was updated".
                    'effective_timestamp': effective_ts,
                    'spec': cleaned,
                    'meta': {
                        "namespace": meta.get("namespace") or "",
                        "uid": meta.get("uid") or "",
                        "deletionTimestamp": meta.get("deletionTimestamp"),
                        "ownerReferences": meta.get("ownerReferences") or [],
                    },
                })
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Always keep deterministic time ordering for lifecycle + diff windows.
        specs.sort(key=lambda s: s["timestamp"])

        last_meta = (specs[-1].get("meta") if specs else {}) or {}
        deletion_ts = last_meta.get("deletionTimestamp")
        deletion_confirmed = deletion_ts is not None and deletion_ts != ""
        
        # Synthetic lifecycle changes (inferred from the window bounds).
        # This allows surfacing objects that were created/deleted during the window,
        # even if we only captured one snapshot or there was no spec diff.
        lifecycle_changes: list[dict[str, Any]] = []
        if inferred_added and pd.notna(first_ts):
            lifecycle_changes.append({
                "timestamp": str(first_ts),
                "from_timestamp": None,
                "changes_truncated": False,
                "change_item_count": 1,
                "change_item_total": 1,
                "changes": [{
                    "path": "entity",
                    "type": "entity_added",
                    "new": entity_id,
                    "inferred": True,
                    "inferred_scope": "window",
                    "evidence": {
                        "first_seen": str(first_ts),
                        "window_first_seen": str(global_min_ts),
                        "window_last_seen": str(global_max_ts),
                    },
                }],
            })
        # Surface deletions even when lifecycle inference is disabled (raw OTEL default),
        # but treat "removed" as "no longer observed" unless we have deletion evidence.
        if (inferred_removed or deletion_confirmed) and pd.notna(last_ts):
            lifecycle_changes.append({
                "timestamp": str(last_ts),
                "from_timestamp": None,
                "changes_truncated": False,
                "change_item_count": 1,
                "change_item_total": 1,
                "changes": [{
                    "path": "entity",
                    "type": "entity_removed",
                    "old": entity_id,
                    "inferred": not deletion_confirmed,
                    "confirmed": bool(deletion_confirmed),
                    "reason": "deletionTimestamp" if deletion_confirmed else "not_observed",
                    "inferred_scope": lifecycle_scope,
                    "evidence": {
                        "last_seen": str(last_ts),
                        "window_first_seen": str(scope_min_ts),
                        "window_last_seen": str(scope_max_ts),
                        "deletionTimestamp": deletion_ts,
                    },
                }],
            })
        
        if len(specs) < 2:
            # Still surface entities that had lifecycle changes within the window.
            if include_no_change or lifecycle_changes:
                parts = entity_id.split("/")
                kind = parts[0] if parts else "Unknown"
                namespace = parts[1] if len(parts) == 3 else ""
                name = parts[-1] if parts else entity_id
                results.append({
                    "entity": entity_id,
                    "kind": kind,
                    "namespace": namespace,
                    "name": name,
                    "first_timestamp": str(first_ts),
                    "last_timestamp": str(last_ts),
                    "observation_count": observation_count,
                    "change_count": len(lifecycle_changes),
                    "duration_sec": (last_ts - first_ts).total_seconds() if pd.notna(first_ts) and pd.notna(last_ts) else 0,
                    "changes": lifecycle_changes,
                    "lifecycle": {
                        "inferred_added": inferred_added,
                        "inferred_removed": inferred_removed,
                    },
                    "reference_spec": {
                        "timestamp": str(specs[0]["timestamp"]),
                        "spec": specs[0]["spec"],
                    } if include_reference_spec and specs else None,
                })
            continue
        
        # Compute diffs between consecutive specs
        all_changes = []
        change_items: list[dict[str, Any]] = []
        
        # Start with lifecycle changes (if any), then append actual diffs.
        all_changes.extend(lifecycle_changes)
        for i in range(1, len(specs)):
            prev_spec = specs[i-1]['spec']
            curr_spec = specs[i]['spec']
            
            if prev_spec == curr_spec:
                continue
            
            diff = _compute_diff(prev_spec, curr_spec)
            if diff:
                event_ts = specs[i].get("timestamp")
                from_event_ts = specs[i - 1].get("timestamp")
                if time_basis == "effective_update":
                    event_ts = specs[i].get("effective_timestamp") or event_ts
                    from_event_ts = specs[i - 1].get("effective_timestamp") or from_event_ts

                limited, truncated, total_items = _apply_change_limit(diff)
                all_changes.append({
                    "timestamp": str(event_ts),
                    "from_timestamp": str(from_event_ts),
                    "changes": limited,
                    "changes_truncated": truncated,
                    "change_item_count": len(limited),
                    "change_item_total": total_items,
                })
                if include_flat_change_items:
                    for item in limited:
                        change_items.append({
                            "timestamp": str(event_ts),
                            "from_timestamp": str(from_event_ts),
                            **item,
                        })

        # If we're using effective_update time basis, filter *change events* by the window,
        # rather than filtering observations. This captures changes whose effects were observed
        # later than their update timestamp.
        if time_basis == "effective_update" and (start_time or end_time):
            start_ts = _to_utc_timestamp(start_time) if start_time else None
            end_ts = _to_utc_timestamp(end_time) if end_time else None

            def _in_window(ts_any: Any) -> bool:
                ts = pd.to_datetime(ts_any, errors="coerce", utc=True)
                if pd.isna(ts):
                    return False
                if start_ts is not None and ts < start_ts:
                    return False
                if end_ts is not None and ts > end_ts:
                    return False
                return True

            all_changes = [w for w in all_changes if _in_window(w.get("timestamp"))]
            if include_flat_change_items:
                change_items = [it for it in change_items if _in_window(it.get("timestamp"))]
        
        if all_changes or include_no_change:
            parts = entity_id.split("/")
            kind = parts[0] if parts else "Unknown"
            namespace = parts[1] if len(parts) == 3 else ""
            name = parts[-1] if parts else entity_id
            
            # Compute total duration of observation
            duration_sec = (last_ts - first_ts).total_seconds() if pd.notna(first_ts) and pd.notna(last_ts) else 0
            
            entity_out: dict[str, Any] = {
                "entity": entity_id,
                "kind": kind,
                "namespace": namespace,
                "name": name,
                "time_basis": time_basis,
                "first_timestamp": str(first_ts),
                "last_timestamp": str(last_ts),
                "observation_count": observation_count,
                "duration_sec": duration_sec,
                "change_count": len(all_changes),
                "changes": all_changes,
            }
            if include_reference_spec and specs:
                entity_out["reference_spec"] = {
                    "timestamp": str(specs[0]["timestamp"]),
                    "spec": specs[0]["spec"],
                }
            if include_flat_change_items:
                entity_out["change_items"] = change_items
                entity_out["change_item_count"] = len(change_items)
            entity_out["lifecycle"] = {
                "inferred_added": inferred_added,
                "inferred_removed": inferred_removed,
            }
            results.append(entity_out)
    
    # Sort deterministically to ensure pagination is stable across calls.
    #
    # Primary goal: avoid duplicate entities across pages due to non-deterministic ordering.
    # Default: entity lexicographic (Kind/name).
    if sort_by == "change_count":
        results.sort(key=lambda x: (-int(x.get("change_count", 0) or 0), str(x.get("entity", "")).lower()))
    else:
        results.sort(key=lambda x: str(x.get("entity", "")).lower())
    
    def _sum_change_events(entities_list: list[dict[str, Any]]) -> int:
        return sum(int(e.get("change_count", 0) or 0) for e in entities_list)
    
    def _sum_change_item_totals(entities_list: list[dict[str, Any]]) -> int:
        total = 0
        for entity in entities_list:
            for window in entity.get("changes", []) or []:
                if isinstance(window, dict):
                    # Prefer the explicit total if present; else fall back to count/len.
                    total += int(
                        window.get("change_item_total")
                        or window.get("change_item_count")
                        or len(window.get("changes", []) or [])
                    )
        return total
    
    total_change_events = _sum_change_events(results)
    total_change_item_total = _sum_change_item_totals(results)
    
    # Apply pagination
    total_count = len(results)
    if offset:
        results = results[offset:]
    if limit:
        results = results[:limit]
    
    returned_change_events = _sum_change_events(results)
    returned_change_item_total = _sum_change_item_totals(results)
    
    # Build an entity-keyed map (ordered by insertion in Python 3.7+).
    # NOTE: JSON object order is not guaranteed by spec, but most consumers preserve it;
    # we still include stable sort + offset/limit to make paging reliable.
    entities_map: dict[str, Any] = {}
    entity_order: list[str] = []
    for entity in results:
        entity_id = str(entity.get("entity", ""))
        if not entity_id:
            continue
        entity_order.append(entity_id)
        changes_detected: dict[str, Any] = {}
        for idx, window in enumerate(entity.get("changes", []) or []):
            if not isinstance(window, dict):
                continue
            ts = str(window.get("timestamp", ""))
            from_ts = str(window.get("from_timestamp", ""))
            # Ensure key uniqueness even if timestamps collide.
            key = f"{ts} (from {from_ts})#{idx}"
            changes_detected[key] = {
                "timestamp": ts,
                "from_timestamp": from_ts,
                "changes_truncated": bool(window.get("changes_truncated", False)),
                "change_item_count": int(window.get("change_item_count", 0) or 0),
                "change_item_total": int(
                    window.get("change_item_total")
                    or window.get("change_item_count")
                    or len(window.get("changes", []) or [])
                ),
                "changes": window.get("changes", []),
            }
        
        entities_map[entity_id] = {
            "kind": entity.get("kind"),
            "name": entity.get("name"),
            "first_timestamp": entity.get("first_timestamp"),
            "last_timestamp": entity.get("last_timestamp"),
            "observation_count": entity.get("observation_count"),
            "duration_sec": entity.get("duration_sec"),
            "change_event_count": entity.get("change_count"),
            "reference_spec": entity.get("reference_spec"),
            "lifecycle": entity.get("lifecycle"),
            "changes_detected": changes_detected,
        }
    
    # Build output
    output = {
        "reference_spec_file": k8s_objects_file,
        "input_format": "raw_otel" if is_raw_otel else "processed",
        "sort_by": sort_by,
        "total_entities_observed": total_entities_observed,
        # Explicit names (requested): total entities with changes + returned entities in this page.
        "num_entities_with_changes": total_count,
        "entities_with_changes_returned": len(results),
        # Explicit stable ordering for page entities (do not rely on JSON object key ordering).
        "entity_order": entity_order,
        "total_change_events": total_change_events,
        "returned_change_events": returned_change_events,
        "total_change_item_total": total_change_item_total,
        "returned_change_item_total": returned_change_item_total,
        # Back-compat keys used by codex-eog pagination logic.
        "total_entities": total_count,
        "returned_count": len(results),
        "offset": offset,
        "limit": limit,
        # Back-compat: array of entity objects (page).
        "entities_with_changes": results,
        # New: entity-keyed map for consumers that prefer dict lookups.
        "entities": entities_map,
    }
    
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


# =============================================================================
# Get Context Contract - Aggregated Context Tool
# =============================================================================

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


def _get_latest_object_def(objects_file: Path, k8_object: str) -> Optional[dict]:
    """Get the latest K8s object definition from objects TSV."""
    if not objects_file or not objects_file.exists():
        return None
    
    try:
        df = pd.read_csv(objects_file, sep='\t')
        df['entity_id'] = df['object_kind'] + '/' + df['object_name']
        
        # Filter by entity
        mask = df['entity_id'].str.lower() == k8_object.lower()
        if not mask.any():
            # Try partial match
            mask = df['entity_id'].str.lower().str.contains(k8_object.lower().split('/')[-1], na=False)
        
        entity_df = df[mask].copy()
        if entity_df.empty:
            return None
        
        # Get latest by timestamp
        entity_df['timestamp'] = pd.to_datetime(entity_df['timestamp'], errors='coerce')
        latest = entity_df.sort_values('timestamp').iloc[-1]
        
        try:
            body = json.loads(latest['body'].replace('""', '"') if isinstance(latest['body'], str) else '{}')
            return {
                "entity": latest['entity_id'],
                "timestamp": str(latest['timestamp']),
                "definition": body
            }
        except (json.JSONDecodeError, TypeError):
            return None
    except Exception:
        return None


async def _get_context_contract(args: dict[str, Any]) -> list[TextContent]:
    """Aggregate full operational context for a K8s entity.
    
    Calls multiple analysis tools internally to build a comprehensive context:
    1. Dependencies (via topology_analysis)
    2. Events (via event_analysis)
    3. Alerts (via alert_analysis)
    4. Trace errors (via get_trace_error_tree)
    5. Metric anomalies (via get_metric_anomalies)
    6. Log patterns (via log_analysis with pattern mining)
    7. K8s object definition (latest from k8s_objects file)
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
    
    # Parse entity kind/namespace/name.
    # Accept:
    # - Kind/name
    # - Kind/namespace/name
    # (and tolerate extra slashes in name by joining remainder)
    parts = [p for p in str(k8_object).split("/") if p]
    entity_kind = parts[0] if parts else "Unknown"
    entity_namespace: str | None = None
    entity_short_name = ""
    if len(parts) == 2:
        entity_short_name = parts[1]
    elif len(parts) >= 3:
        entity_namespace = parts[1]
        entity_short_name = "/".join(parts[2:])
    else:
        entity_short_name = k8_object

    # Name used for searching/filtering across traces/metrics/events (usually service/deploy name).
    entity_search_name = entity_short_name
    # Display name (keep namespace if provided).
    entity_display_name = (
        f"{entity_namespace}/{entity_short_name}" if entity_namespace else entity_short_name
    )
    
    result: dict[str, Any] = {
        "entity": k8_object,
        "kind": entity_kind,
        "name": entity_display_name,
        "page": page,
        "snapshot_dir": str(snapshot_dir),
        "time_window": {
            "start": start_time,
            "end": end_time
        },
        "files_found": {k: str(v) if v else None for k, v in files.items()},
    }
    
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
            topo_result = await _topology_analysis({
                "topology_file": str(files["topology_file"]),
                "entity": entity_search_name
            })
            topo_text = topo_result[0].text
            topo_data = json.loads(topo_text)
            
            # Get deps from the entity itself (calls, depends_on)
            direct_deps = _extract_functional_deps(topo_data)
            
            # Also get deps from the backing infrastructure pods
            # (depends_on relationships are often at Pod level)
            backing_pods = _extract_pods_from_backing_infra(topo_data)
            for pod_id in backing_pods[:3]:  # Limit to first 3 pods to avoid explosion
                try:
                    pod_topo_result = await _topology_analysis({
                        "topology_file": str(files["topology_file"]),
                        "entity": pod_id
                    })
                    pod_topo_data = json.loads(pod_topo_result[0].text)
                    pod_deps = _extract_functional_deps(pod_topo_data)
                    direct_deps.update(pod_deps)
                except Exception:
                    pass
            
            # Get transitive dependencies (hop 1) - deps of our direct deps
            for dep in list(direct_deps):
                try:
                    dep_topo_result = await _topology_analysis({
                        "topology_file": str(files["topology_file"]),
                        "entity": dep
                    })
                    dep_topo_data = json.loads(dep_topo_result[0].text)
                    
                    # Get this dep's dependencies (including from its pods)
                    dep_deps = _extract_functional_deps(dep_topo_data)
                    
                    # Also check backing pods of this dependency
                    dep_pods = _extract_pods_from_backing_infra(dep_topo_data)
                    for pod_id in dep_pods[:2]:  # Limit to 2 pods per dep
                        try:
                            pod_topo_result = await _topology_analysis({
                                "topology_file": str(files["topology_file"]),
                                "entity": pod_id
                            })
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
                    "transitive": sorted(list(transitive_deps))
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
        "all_pages": page == 0
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
                        name_variants.append(base_name[:-len(suffix)])
                
                events_data = []
                for variant in name_variants:
                    event_result = await _event_analysis({
                        **event_args,
                        "filters": {"deployment": variant} if entity_kind in ["Deployment", "Service", "App"] else {"object_name": variant}
                    })
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
                        "total_count": len(events_data)
                    },
                    "truncated": False
                }
            except Exception as e:
                result["events_error"] = str(e)
        
        # 2. Alerts
        if files["alerts_dir"]:
            try:
                alert_args = {
                    "base_dir": str(files["alerts_dir"]),
                    "limit": 20
                }
                if start_time:
                    alert_args["start_time"] = start_time
                if end_time:
                    alert_args["end_time"] = end_time
                
                alert_result = await _alert_analysis(alert_args)
                alerts_data = json.loads(alert_result[0].text)
                
                # Filter alerts related to this entity
                related_alerts = [
                    a for a in alerts_data 
                    if entity_name.lower() in str(a).lower()
                ]
                
                result["alerts"] = {
                    "total_alerts": len(alerts_data),
                    "related_to_entity": len(related_alerts),
                    "items": related_alerts[:10],
                    "truncated": len(related_alerts) > 10
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
                        name_variants.append(base_name[:-len(suffix)])
                
                trace_data = None
                for variant in name_variants:
                    trace_args = {
                        "trace_file": str(files["traces_file"]),
                        "service_name": variant
                    }
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
                    result["trace_errors"] = {"message": "No trace data found for entity", "variants_tried": name_variants}
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
                        name_variants.append(base_name[:-len(suffix)])
                
                async def _try_metric_target(k8_obj_name: str) -> dict[str, Any] | None:
                    anomaly_args = {"base_dir": str(files["metrics_dir"]), "k8_object_name": k8_obj_name, "raw_content": False}
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
                    "similarity_threshold": 0.5
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
                        "patterns": log_data.get("patterns", [])
                    }
                else:
                    result["log_patterns"] = {
                        "total_logs": 0,
                        "message": "No logs found for entity in time window"
                    }
            except Exception as e:
                result["log_patterns_error"] = str(e)
        
        # 6. Latest K8s object definition
        if files["objects_file"]:
            latest_def = _get_latest_object_def(files["objects_file"], k8_object)
            if latest_def:
                # Truncate large definitions
                def_str = json.dumps(latest_def.get("definition", {}))
                if len(def_str) > 2000:
                    result["k8s_object_definition"] = {
                        "entity": latest_def["entity"],
                        "timestamp": latest_def["timestamp"],
                        "definition_truncated": True,
                        "definition_preview": def_str[:2000] + "..."
                    }
                else:
                    result["k8s_object_definition"] = latest_def
        
        # 7. Spec changes
        if files["objects_file"]:
            try:
                spec_args = {
                    "k8s_objects_file": str(files["objects_file"]),
                    "k8_object_name": k8_object
                }
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
                            "filters": {"deployment": dep} if not dep.startswith("Pod/") else {"object_name": dep.split("/")[-1]},
                            "limit": 10
                        }
                        if start_time:
                            event_args["start_time"] = start_time
                        if end_time:
                            event_args["end_time"] = end_time
                        
                        event_result = await _event_analysis(event_args)
                        events_data = json.loads(event_result[0].text)
                        dep_context["events"] = {
                            "count": len(events_data),
                            "items": events_data[:5]
                        }
                    except Exception as e:
                        dep_context["events_error"] = str(e)
                
                # Spec changes for dependency
                if files["objects_file"]:
                    try:
                        spec_args = {
                            "k8s_objects_file": str(files["objects_file"]),
                            "k8_object_name": dep
                        }
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
                        "filters": {"deployment": dep} if not dep.startswith("Pod/") else {"object_name": dep.split("/")[-1]},
                        "limit": 10
                    }
                    if start_time:
                        event_args["start_time"] = start_time
                    if end_time:
                        event_args["end_time"] = end_time
                    
                    event_result = await _event_analysis(event_args)
                    events_data = json.loads(event_result[0].text)
                    dep_context["events"] = {
                        "count": len(events_data),
                        "items": events_data[:5]
                    }
                except Exception as e:
                    dep_context["events_error"] = str(e)
            
            # Spec changes for dependency
            if files["objects_file"]:
                try:
                    spec_args = {
                        "k8s_objects_file": str(files["objects_file"]),
                        "k8_object_name": dep
                    }
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
        >>> from sre_tools.cli.sre_utils.tools import build_topology_standalone
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

def _cli_build_topology(args) -> int:
    """CLI handler for build_topology command."""
    try:
        topology = build_topology_standalone(
            arch_file=args.arch_file,
            k8s_objects_file=args.k8s_objects_file,
            output_file=args.output_file
        )
        print(f"✓ Topology written to {args.output_file}")
        print(f"  Nodes: {len(topology['nodes'])}")
        print(f"  Edges: {len(topology['edges'])}")
        return 0
    except FileNotFoundError as e:
        print(f"✗ File not found: {e}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1


def _cli_get_context_contract(args) -> int:
    """CLI handler for get_context_contract command."""
    import asyncio
    
    try:
        # Build arguments dict
        arguments = {
            "k8_object": args.k8_object,
            "snapshot_dir": args.snapshot_dir,
        }
        if args.topology_file:
            arguments["topology_file"] = args.topology_file
        if args.start_time:
            arguments["start_time"] = args.start_time
        if args.end_time:
            arguments["end_time"] = args.end_time
        if args.page is not None:
            arguments["page"] = args.page
        if args.deps_per_page is not None:
            arguments["deps_per_page"] = args.deps_per_page
        
        # Run async function
        result = asyncio.run(_get_context_contract(arguments))
        
        # Print result
        for content in result:
            print(content.text)
        
        return 0
    except FileNotFoundError as e:
        print(f"✗ File not found: {e}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    """Command-line interface for SRE utility tools."""
    import argparse
    
    parser = argparse.ArgumentParser(
        prog="sre_utils",
        description="SRE utility tools for incident investigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build topology from architecture and K8s objects
  python -m sre_tools.cli.sre_utils.tools build_topology \\
    --arch-file app/arch.json \\
    --k8s-objects-file k8s_objects.tsv \\
    --output-file topology.json

  # List available tools
  python -m sre_tools.cli.sre_utils.tools --list
        """
    )
    
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available tools"
    )
    
    subparsers = parser.add_subparsers(
        title="tools",
        dest="tool",
        description="Available tools (use '<tool> --help' for tool-specific help)"
    )
    
    # build_topology subcommand
    build_topo_parser = subparsers.add_parser(
        "build_topology",
        help="Build operational topology from application architecture and K8s objects",
        description="Creates a topology graph with nodes (services, pods, deployments) and edges (relationships)"
    )
    build_topo_parser.add_argument(
        "--arch-file", "-a",
        required=True,
        help="Path to application architecture JSON file"
    )
    build_topo_parser.add_argument(
        "--k8s-objects-file", "-k",
        required=True,
        help="Path to Kubernetes objects TSV file"
    )
    build_topo_parser.add_argument(
        "--output-file", "-o",
        required=True,
        help="Path to write the topology JSON output"
    )
    build_topo_parser.set_defaults(func=_cli_build_topology)
    
    # get_context_contract subcommand
    context_parser = subparsers.add_parser(
        "get_context_contract",
        help="Get full operational context for a K8s entity",
        description="Aggregates events, alerts, traces, metrics, spec changes, and dependencies for an entity"
    )
    context_parser.add_argument(
        "--k8-object", "-k",
        required=True,
        help="K8s object in Kind/name format (e.g., 'Deployment/cart', 'Service/frontend')"
    )
    context_parser.add_argument(
        "--snapshot-dir", "-s",
        required=True,
        help="Path to snapshot directory containing k8s_events*.tsv, k8s_objects*.tsv, etc."
    )
    context_parser.add_argument(
        "--topology-file", "-t",
        help="Path to topology JSON (optional, will auto-build if not provided)"
    )
    context_parser.add_argument(
        "--start-time",
        help="Start timestamp (ISO 8601)"
    )
    context_parser.add_argument(
        "--end-time",
        help="End timestamp (ISO 8601)"
    )
    context_parser.add_argument(
        "--page", "-p",
        type=int,
        default=1,
        help="Page number: 0=all, 1=main entity, 2+=dependencies (default: 1)"
    )
    context_parser.add_argument(
        "--deps-per-page",
        type=int,
        default=3,
        help="Dependencies per page for page >= 2 (default: 3)"
    )
    context_parser.set_defaults(func=_cli_get_context_contract)
    
    # Parse args
    args = parser.parse_args()
    
    # Handle --list
    if args.list:
        print("Available tools:")
        print()
        print("  build_topology         - Build operational topology from architecture and K8s objects")
        print("  topology_analysis      - Analyze topology (dependencies, service context, infra hierarchy)")
        print("  metric_analysis        - General metric analysis (filtering, grouping, math)")
        print("  get_metric_anomalies   - Focused anomaly detection")
        print("  event_analysis         - Analyze K8s events (filter, group, aggregate)")
        print("  get_trace_error_tree   - Trace error analysis")
        print("  alert_analysis         - Analyze alerts (filter, group, aggregate, duration)")
        print("  alert_summary          - Summarize alerts by entity (counts, severity breakdown)")
        print("  k8s_spec_change_analysis - Detect K8s spec changes (image, replicas, env, resources)")
        print("  get_context_contract   - Full context for an entity (events, alerts, traces, metrics, deps)")
        print()
        print("Use '<tool> --help' for tool-specific options.")
        return 0
    
    # No tool specified
    if not args.tool:
        parser.print_help()
        return 0
    
    # Run the tool
    return args.func(args)


if __name__ == "__main__":
    exit(main())
