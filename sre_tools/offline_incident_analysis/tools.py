"""
SRE utility tool implementations for offline incident analysis.

Provides MCP tools for:
- Topology building and analysis
- Metric analysis and anomaly detection
- Kubernetes event analysis
- Log analysis with pattern mining
- Distributed trace analysis
- Alert analysis and summarization
- K8s spec change tracking
- Context aggregation across data sources

Usage:
- MCP server: python -m sre_tools.offline_incident_analysis
- Python API: from sre_tools.offline_incident_analysis.tools import build_topology_standalone
- CLI: python -m sre_tools.offline_incident_analysis.tools build_topology --help
"""

from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

# Import handler functions from domain modules
from .alerts.analyzer import _alert_analysis, _alert_summary
from .context.aggregator import _get_context_contract
from .events.analyzer import _event_analysis
from .k8s_specs.change_analyzer import _k8s_spec_change_analysis
from .k8s_specs.retriever import _get_k8_spec
from .logs.analyzer import _log_analysis
from .metrics.analyzer import _metric_analysis
from .metrics.anomalies import _get_metric_anomalies
from .topology.analyzer import _topology_analysis
from .topology.builder import build_topology_standalone
from .topology.tools import _build_topology
from .traces.analyzer import _get_trace_error_tree


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
                            "description": "Path to metrics directory (e.g., metrics/) containing pod_*.tsv and service_*.tsv files",
                        },
                        "k8_object_name": {
                            "type": "string",
                            "description": "Optional: Specific K8s object. Formats: 'namespace/kind/name' (preferred), 'kind/name', or 'name'. Omit to analyze ALL objects.",
                        },
                        "object_pattern": {
                            "type": "string",
                            "description": "Optional: Glob pattern for objects (e.g., 'pod/*', 'pod/frontend*', 'service/*'). Default: '*' (all)",
                        },
                        "metric_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional: List of metric names to load. If omitted, loads all metrics.",
                        },
                        "eval": {
                            "type": "string",
                            "description": "Optional: Pandas eval string for derived metrics (e.g. 'throttling_pct = throttled / total * 100')",
                        },
                        "filters": {
                            "type": "object",
                            "description": "Optional: Dictionary of exact matches for columns",
                        },
                        "group_by": {
                            "type": "string",
                            "description": "Optional: Column to group by. Special values: 'deployment' (auto-extracted from pod name), 'pod_name', 'metric_name'",
                        },
                        "agg": {
                            "type": "string",
                            "description": "Optional: Aggregation function (mean, sum, max, min). Default: mean",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC).",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC).",
                        },
                        "verbosity": {
                            "type": "string",
                            "description": "Optional: Output verbosity. 'compact' is optimized for LLMs (drops buckets by default, filters tags->labels, dedupes, applies limit). Use 'raw' for the full row output.",
                            "default": "compact",
                            "enum": ["compact", "raw"],
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max number of rows to return in compact mode. Use 0 for no limit.",
                            "default": 200,
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Optional: Column to sort by (descending) before applying limit in compact mode.",
                        },
                        "include_tags": {
                            "type": "boolean",
                            "description": "Optional: Keep the original verbose `tags` column in compact mode. Default: false (drop tags and emit filtered `labels` instead).",
                            "default": False,
                        },
                        "include_buckets": {
                            "type": "boolean",
                            "description": "Optional: Include histogram bucket metrics (metric_name ending with '_bucket') in compact mode. Default: false.",
                            "default": False,
                        },
                        "labels_keep": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional: Allowlist of tag keys to keep in the emitted `labels` field (compact mode).",
                        },
                    },
                    "required": ["base_dir"],
                },
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
                            "description": "K8s object identifier. Formats: 'namespace/kind/name' (preferred), 'kind/name', or 'name'",
                        },
                        "base_dir": {
                            "type": "string",
                            "description": "Path to metrics directory (e.g., metrics/) containing pod_*.tsv and service_*.tsv files",
                        },
                        "metric_name_filter": {
                            "type": "string",
                            "description": "Optional: Only analyze metrics matching this name/substring",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC).",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Can only be given if start_time is present. Examples: '2025-12-12T02:45:00Z' (UTC).",
                        },
                        "raw_content": {
                            "type": "boolean",
                            "description": "Optional: Include raw metric time series data (default: true)",
                            "default": True,
                        },
                    },
                    "required": ["k8_object_name", "base_dir"],
                },
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
                            "description": "Path to Kubernetes events TSV file (e.g., k8s_events.tsv)",
                        },
                        "filters": {
                            "type": "object",
                            "description": "Optional: Column filters (e.g. {'reason': 'Unhealthy', 'event_kind': 'Warning', 'namespace': 'otel-demo'})",
                        },
                        "group_by": {
                            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                            "description": "Optional: Column(s) to group by. String or list. Special: 'deployment' extracts from pod names.",
                        },
                        "agg": {
                            "type": "string",
                            "description": "Optional: Aggregation type - 'count' (default), 'first', 'last', 'nunique', 'list'",
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Optional: Column to sort by. Default: 'count' desc for grouped, 'timestamp' for raw.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max rows to return. Use 0 to fetch all rows (no limit). Default: no limit.",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N rows (pagination). Default: 0",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC). Use 'Z' suffix or explicit timezone offset for clarity.",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC). Use 'Z' suffix or explicit timezone offset for clarity.",
                        },
                    },
                    "required": ["events_file"],
                },
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
                            "description": "Path to OTEL logs TSV file (e.g., otel_logs_raw.tsv)",
                        },
                        "k8_object": {
                            "type": "string",
                            "description": "Optional: K8s object identifier. Formats: 'namespace/kind/name' (preferred), 'kind/name', or 'name'. Matches against k8s.deployment.name or k8s.pod.name in ResourceAttributes.",
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Optional: Filter by ServiceName column (e.g., 'recommendation', 'cart')",
                        },
                        "severity_filter": {
                            "type": "string",
                            "description": "Optional: Filter by SeverityText (e.g., 'ERROR', 'WARNING', 'INFO'). Can be comma-separated for multiple: 'ERROR,WARNING'",
                        },
                        "body_contains": {
                            "type": "string",
                            "description": "Optional: Case-insensitive substring search in log Body",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format (e.g., '2025-12-15T17:15:00Z')",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format (e.g., '2025-12-15T17:35:00Z')",
                        },
                        "pattern_analysis": {
                            "type": "boolean",
                            "description": "Optional: Enable log pattern mining (default: true). When true, clusters logs into patterns with counts and examples. When false, returns raw logs with pagination.",
                            "default": True,
                        },
                        "max_patterns": {
                            "type": "integer",
                            "description": "Optional: Maximum patterns to return when pattern_analysis=true. Default: 50. Patterns are sorted by count (most frequent first).",
                        },
                        "similarity_threshold": {
                            "type": "number",
                            "description": "Optional: Similarity threshold for pattern clustering (0.0-1.0). Lower values create more specific patterns. Default: 0.5",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max rows to return (only when pattern_analysis=false). Default: 100. Use 0 for no limit.",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N rows (only when pattern_analysis=false). Default: 0",
                        },
                    },
                    "required": ["logs_file"],
                },
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
                            "description": "Path to OpenTelemetry traces TSV file (e.g., otel_traces.tsv)",
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Optional: Filter to only include traces that CONTAIN this service (shows full lineage including upstream callers)",
                        },
                        "span_kind": {
                            "type": "string",
                            "description": "Optional: Filter spans by kind (Client, Server, Internal).",
                            "enum": ["Client", "Server", "Internal"],
                        },
                        "pivot_time": {
                            "type": "string",
                            "description": "Highly recommended: Pivot timestamp for before/after comparison (ISO 8601). Required for regression analysis.",
                        },
                        "delta_time": {
                            "type": "string",
                            "description": "Optional: Duration for comparison window (e.g., '5m', '10m', '1h'). Default: 5m",
                            "default": "5m",
                        },
                        "error_threshold_pct": {
                            "type": "number",
                            "description": "Optional: Only show paths where error rate changed by more than this percentage. Default: 10",
                            "default": 10,
                        },
                        "latency_threshold_pct": {
                            "type": "number",
                            "description": "Optional: Only show paths where latency changed by more than this percentage. Default: 10",
                            "default": 10,
                        },
                    },
                    "required": ["trace_file"],
                },
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
                            "description": "Path to alerts directory (e.g., alerts/) containing alerts_at_*.json files, OR snapshot directory (auto-detects 'alerts/' subdirectory)",
                        },
                        "time_basis": {
                            "type": "string",
                            "description": "Optional: Which timestamp to use for time window filtering and default ordering. "
                            "'snapshot' uses observation time (API response timestamp or alerts_at_* filename). "
                            "'activeAt' uses when the alert first became active in Alertmanager/Prometheus. "
                            "Default: snapshot.",
                            "enum": ["snapshot", "activeAt"],
                            "default": "snapshot",
                        },
                        "filters": {
                            "type": "object",
                            "description": "Optional: Column filters (e.g. {'state': 'firing', 'severity': 'critical'})",
                        },
                        "group_by": {
                            "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                            "description": "Optional: Column(s) to group by. Shortcuts: alertname, severity, service_name, namespace.",
                        },
                        "agg": {
                            "type": "string",
                            "description": "Optional: Aggregation - 'count' (default), 'first', 'last', 'sum', 'mean', 'max', 'min'",
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Optional: Column to sort by (e.g. 'duration_active_min', 'count')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max rows to return. Use 0 to fetch all rows (no limit). Default: no limit.",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N rows (pagination). Default: 0",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Filter alerts after this time (ISO 8601). "
                            "By default this applies to snapshot/observation time (time_basis='snapshot'). "
                            "Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC).",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: Filter alerts before this time (ISO 8601). "
                            "By default this applies to snapshot/observation time (time_basis='snapshot'). "
                            "Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC).",
                        },
                    },
                    "required": ["base_dir"],
                },
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
                            "description": "Path to alerts directory (e.g., alerts/) containing alerts_at_*.json files, OR snapshot directory (auto-detects 'alerts/' subdirectory)",
                        },
                        "time_basis": {
                            "type": "string",
                            "description": "Optional: Which timestamp to use for first_seen/last_seen/duration_min. "
                            "'snapshot' uses observation time (recommended). "
                            "'activeAt' uses when the alert first became active. Default: snapshot.",
                            "enum": ["snapshot", "activeAt"],
                            "default": "snapshot",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp (ISO 8601) for filtering. "
                            "Applies to snapshot time by default (time_basis='snapshot').",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp (ISO 8601) for filtering. "
                            "Applies to snapshot time by default (time_basis='snapshot').",
                        },
                        "state_filter": {
                            "type": "string",
                            "description": "Optional: Filter by state ('firing', 'pending', 'inactive'). Default: show all.",
                        },
                        "min_duration_min": {
                            "type": "number",
                            "description": "Optional: Only show alerts active for at least this many minutes",
                        },
                        "limit": {"type": "integer", "description": "Optional: Max alerts to return. Default: 50"},
                    },
                    "required": ["base_dir"],
                },
            ),
            Tool(
                name="k8s_spec_change_analysis",
                description="Analyzes Kubernetes object spec changes over time. "
                "Detects and reports meaningful spec changes, filtering out timestamp-related churn. "
                "Groups by entity, computes diffs between consecutive specs, and reports duration. "
                "Supports multiple identifier formats: namespace/kind/name (PREFERRED), kind/name, or name. "
                "Example: Find all spec changes: k8s_objects_file='k8s_objects.tsv'. "
                "Example (preferred): k8_object_name='otel-demo/Deployment/cart'. "
                "Example (ambiguous): k8_object_name='Deployment/cart' - returns changes for all matching objects. "
                "Useful for: identifying config drift, tracking rollouts, correlating incidents with changes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "k8s_objects_file": {
                            "type": "string",
                            "description": "Path to Kubernetes objects TSV file (e.g., k8s_objects.tsv)",
                        },
                        "k8_object_name": {
                            "type": "string",
                            "description": "Optional: Filter by specific object. Formats: 'namespace/kind/name' (PREFERRED), 'kind/name', or 'name'",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC).",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Requires start_time. Examples: '2025-12-12T02:45:00Z' (UTC).",
                        },
                        "max_changes_per_diff": {
                            "type": "integer",
                            "description": "Optional: Cap the number of change items returned per diff window. If omitted, returns all change items (can be large).",
                        },
                        "include_reference_spec": {
                            "type": "boolean",
                            "description": "Optional: Include the baseline (reference) spec used for diffing. Default: true.",
                        },
                        "include_flat_change_items": {
                            "type": "boolean",
                            "description": "Optional: Include a flat list of all change items (path/type/old/new) with timestamps for easier programmatic consumption. Default: true.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional: Max number of entities with changes to return (pagination)",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional: Skip first N entities (pagination). Default: 0",
                        },
                        "include_no_change": {
                            "type": "boolean",
                            "description": "Optional: Include entities with no spec changes (default: false)",
                        },
                    },
                    "required": ["k8s_objects_file"],
                },
            ),
            Tool(
                name="get_context_contract",
                description="Aggregates full operational context for a K8s entity by calling multiple analysis tools. "
                "Returns: events, alerts, trace errors, metric anomalies, K8s object spec, spec changes, "
                "and dependency context. Uses existing tools internally (topology_analysis, event_analysis, etc.). "
                "Supports identifier formats: namespace/kind/name (PREFERRED), kind/name, or name. "
                "Example (preferred): k8_object='otel-demo/Service/cart', snapshot_dir='/path/to/snapshot'. "
                "Example (ambiguous): k8_object='Service/cart' - may match multiple namespaces. "
                "Pagination: page=1 returns main entity context, page=2+ returns dependency context.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "k8_object": {
                            "type": "string",
                            "description": "K8s object identifier. Formats: 'namespace/kind/name' (PREFERRED), 'kind/name', or 'name'",
                        },
                        "snapshot_dir": {
                            "type": "string",
                            "description": "Path to snapshot directory containing k8s_events.tsv, k8s_objects.tsv, otel_traces.tsv, alerts/, metrics/",
                        },
                        "topology_file": {
                            "type": "string",
                            "description": "Optional: Path to topology JSON file (e.g., operational_topology.json). If not provided, will look in snapshot_dir or build one.",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Optional: Start timestamp in ISO 8601 format. Examples: '2025-12-12T02:30:00Z' (UTC) or '2025-12-12 02:30:00' (naive, treated as UTC).",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Optional: End timestamp in ISO 8601 format. Examples: '2025-12-12T02:45:00Z' (UTC) or '2025-12-12 02:45:00' (naive, treated as UTC).",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Optional: Page number. Page 0 = ALL pages at once, Page 1 = main entity, Page 2+ = dependencies. Default: 1",
                        },
                        "deps_per_page": {
                            "type": "integer",
                            "description": "Optional: Number of dependencies per page (for page >= 2). Default: 3. Ignored if page=0.",
                        },
                    },
                    "required": ["k8_object", "snapshot_dir"],
                },
            ),
            Tool(
                name="get_k8_spec",
                description="Retrieves the Kubernetes spec for a specific resource. "
                "Supports multiple identifier formats: namespace/kind/name (PREFERRED), kind/name, or name. "
                "Returns the latest spec by default, or all observations if requested. "
                "For ambiguous formats (kind/name or name), returns ALL matching resources. "
                "Example (preferred): k8_object_name='otel-demo/Service/cart'. "
                "Example (ambiguous): k8_object_name='Service/cart' - returns all Services named 'cart' across namespaces. "
                "Useful for: inspecting current resource configuration, debugging deployments.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "k8s_objects_file": {
                            "type": "string",
                            "description": "Path to Kubernetes objects TSV file (e.g., k8s_objects_raw.tsv)",
                        },
                        "k8_object_name": {
                            "type": "string",
                            "description": "K8s resource identifier. Formats: 'namespace/kind/name' (PREFERRED, e.g., 'otel-demo/Deployment/cart'), 'kind/name' (ambiguous, e.g., 'Deployment/cart'), or 'name' (most ambiguous)",
                        },
                        "return_all_observations": {
                            "type": "boolean",
                            "description": "Optional: If true, return all observations over time instead of just the latest. Default: false",
                        },
                        "include_metadata": {
                            "type": "boolean",
                            "description": "Optional: If true, include full metadata in response. Default: true",
                        },
                    },
                    "required": ["k8s_objects_file", "k8_object_name"],
                },
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
        elif name == "get_k8_spec":
            return await _get_k8_spec(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


def main():
    """Command-line interface for SRE utility tools."""
    import argparse

    from .context.cli import _cli_get_context_contract
    from .topology.cli import _cli_build_topology

    parser = argparse.ArgumentParser(
        prog="offline_incident_analysis",
        description="SRE utility tools for incident investigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build topology from architecture and K8s objects
  python -m sre_tools.offline_incident_analysis.tools build_topology \\
    --arch-file app/arch.json \\
    --k8s-objects-file k8s_objects.tsv \\
    --output-file topology.json

  # List available tools
  python -m sre_tools.offline_incident_analysis.tools --list
        """,
    )

    parser.add_argument("--list", "-l", action="store_true", help="List available tools")

    subparsers = parser.add_subparsers(
        title="tools", dest="tool", description="Available tools (use '<tool> --help' for tool-specific help)"
    )

    # build_topology subcommand
    build_topo_parser = subparsers.add_parser(
        "build_topology",
        help="Build operational topology from application architecture and K8s objects",
        description="Creates a topology graph with nodes (services, pods, deployments) and edges (relationships)",
    )
    build_topo_parser.add_argument(
        "--arch-file", "-a", required=True, help="Path to application architecture JSON file"
    )
    build_topo_parser.add_argument(
        "--k8s-objects-file", "-k", required=True, help="Path to Kubernetes objects TSV file"
    )
    build_topo_parser.add_argument("--output-file", "-o", required=True, help="Path to write the topology JSON output")
    build_topo_parser.set_defaults(func=_cli_build_topology)

    # get_context_contract subcommand
    context_parser = subparsers.add_parser(
        "get_context_contract",
        help="Get full operational context for a K8s entity",
        description="Aggregates events, alerts, traces, metrics, spec changes, and dependencies for an entity",
    )
    context_parser.add_argument(
        "--k8-object",
        "-k",
        required=True,
        help="K8s object in Kind/name format (e.g., 'Deployment/cart', 'Service/frontend')",
    )
    context_parser.add_argument(
        "--snapshot-dir",
        "-s",
        required=True,
        help="Path to snapshot directory containing k8s_events*.tsv, k8s_objects*.tsv, etc.",
    )
    context_parser.add_argument(
        "--topology-file", "-t", help="Path to topology JSON (optional, will auto-build if not provided)"
    )
    context_parser.add_argument("--start-time", help="Start timestamp (ISO 8601)")
    context_parser.add_argument("--end-time", help="End timestamp (ISO 8601)")
    context_parser.add_argument(
        "--page", "-p", type=int, default=1, help="Page number: 0=all, 1=main entity, 2+=dependencies (default: 1)"
    )
    context_parser.add_argument(
        "--deps-per-page", type=int, default=3, help="Dependencies per page for page >= 2 (default: 3)"
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
        print("  get_k8_spec            - Retrieve K8s spec for a resource (Kind/name format)")
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
