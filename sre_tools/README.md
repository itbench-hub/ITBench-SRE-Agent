# SRE Tools - MCP Tools for Zero Agent

This package provides modular MCP (Model Context Protocol) tools that extend the Zero agent with specialized capabilities for SRE incident investigation.

## Installation

The sre_tools package and its dependencies are included in the main project. Install with:

```bash
# From the project root
pip install -e .

# Or with uv
uv pip install -e .
```

This installs:
- `sre_tools` package (local MCP tools)
- `mcp` library (MCP protocol implementation)
- `zero` CLI

## Quick Start

The `offline_incident_analysis` MCP server is automatically configured when using Zero. You can also run it standalone:

```bash
# Run the MCP server directly (for testing)
python -m sre_tools.offline_incident_analysis

# Or use with Zero
python -m zero --workspace /tmp/work --read-only-dir /path/to/scenario
```

## Available Tools

### K8s Object Identifier Formats

All tools that accept K8s object identifiers (`k8_object`, `k8_object_name`) support three formats:

| Format | Example | Behavior |
|--------|---------|----------|
| `namespace/kind/name` | `otel-demo/Service/cart` | **PREFERRED** - Unambiguous, returns exact match |
| `kind/name` | `Service/cart` | Ambiguous - Returns ALL matches across namespaces (with warning) |
| `name` | `cart` | Most ambiguous - Returns ALL matches across kinds and namespaces (with warning) |

**Recommendation:** Always use `namespace/kind/name` format for precise results. The ambiguous formats are supported for convenience but return multiple matches when the identifier exists in multiple namespaces or as different resource kinds.

---

### 1. `offline_incident_analysis` - SRE Utility Functions

**Type:** Local Python MCP Server (stdio)

Provides tools for building operational topology graphs and analyzing observability data.

#### Tools Provided

| Tool | Description |
|------|-------------|
| `build_topology` | Build operational topology graph from app architecture and K8s objects |
| `topology_analysis` | Analyze topology (dependencies, service context, K8s hierarchy) |
| `metric_analysis` | Analyze metrics with filtering, grouping, derived metrics |
| `get_metric_anomalies` | Focused anomaly detection for metrics |
| `event_analysis` | Analyze K8s events with filtering, grouping, aggregation |
| `get_trace_error_tree` | Analyze traces with error tree, latency percentiles (p50/p90/p99), and pre/post comparison |
| `alert_summary` | **Start here for alerts** - High-level summary: type, entity, duration, frequency |
| `alert_analysis` | Analyze alerts with filtering, grouping, duration tracking |
| `k8s_spec_change_analysis` | Track K8s object spec changes over time (config drift, rollouts) |
| `get_k8_spec` | Retrieve the K8s spec for a specific resource by Kind/name |
| `get_context_contract` | **Aggregation tool** - Full context for an entity (events, alerts, traces, metrics, spec changes, dependencies) |

#### Usage with Zero

The `offline_incident_analysis` MCP server is automatically enabled via Zero's configuration:

```bash
python -m zero --workspace /tmp/work --read-only-dir /path/to/scenario
```

#### Tool Details

**1. build_topology**

Creates an operational topology graph.

- `arch_file` (Required): Path to application architecture JSON.
- `k8s_objects_file` (Required): Path to K8s objects TSV.
- `output_file` (Required): Path to write JSON topology.

**1b. topology_analysis**

Analyzes the operational topology graph to understand entity relationships.
Three modes: `dependencies`, `service_context`, `infra_context`.

**Tip:** If topology_file doesn't exist, first build it with `build_topology` (only needs to be built once per scenario).

**Mode: dependencies** - Find what an entity depends on up to K hops.
```python
topology_analysis(topology_file="topology.json", entity="checkout", mode="dependencies", hops=2)
# Returns:
# {
#   "entity": "frontend",
#   "depends_on": {"direct": ["product-catalog", "checkout", ...], "transitive": []},
#   "dependents": {"direct": ["load-generator"], "transitive": []}
# }
```

**Mode: service_context** - Analyze the service call graph: roots (entry points), leaves (backends), call chains.
```python
# Full call graph summary
topology_analysis(topology_file="topology.json", mode="service_context")
# Returns: {"root_services": ["frontend-proxy", "load-generator"], "leaf_services": ["kafka", "postgresql"]}

# Call chain for specific service
topology_analysis(topology_file="topology.json", entity="checkout", mode="service_context")
# Returns: callers, callees, paths_from_root, paths_to_leaf
```

**Mode: infra_context** - Navigate K8s hierarchy (Namespace → Deployment → ReplicaSet → Pod → Node).
```python
# For a Pod
topology_analysis(topology_file="topology.json", entity="checkout-8546fdc74d-7m4dn", mode="infra_context")
# Returns:
# {
#   "hierarchy": {"namespace": "otel-demo", "deployment": "checkout", "node": "i-05b952ba5be50b546"},
#   "dependencies": {"ConfigMap": [...], "Service": ["otel-collector", "kafka"]}
# }
```

- `topology_file` (Required): Path to topology JSON (output from build_topology).
- `entity` (Optional for service_context): Entity name to analyze.
- `mode` (Required): Analysis mode.
- `hops` (Optional): Max hops for dependencies mode (default: 2).
- `direction` (Optional): "outgoing", "incoming", or "both" (default).

**2. metric_analysis**

Analyzes metrics across K8s objects. Supports **batch queries across ALL objects**, filtering, grouping, aggregation, and derived metrics.

**Key Feature:** Query ALL pods at once with `object_pattern='pod/*'` and get aggregated results per deployment.

**Works like SQL/Pandas: filter → eval → group_by → agg**

**Example 1: Peak Cluster Memory Utilization**
```python
metric_analysis(
    base_dir="path/to/metrics",
    object_pattern="pod/*",
    metric_names=["container_memory_usage_bytes", "cluster:namespace:pod_memory:active:kube_pod_container_resource_limits"],
    eval="mem_pct = container_memory_usage_bytes / cluster_namespace_pod_memory_active_kube_pod_container_resource_limits * 100",
    agg="max"  # No group_by → aggregates across entire cluster
)
# Returns: [{"mem_pct": 25.5, ...}]  (peak cluster-wide memory utilization)
```

**Example 2: CPU Throttling Per Deployment**
```python
metric_analysis(
    base_dir="path/to/metrics",
    object_pattern="pod/*",
    metric_names=["container_cpu_cfs_throttled_periods_total", "container_cpu_cfs_periods_total"],
    eval="throttle_pct = container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total * 100",
    group_by="deployment",  # Per-deployment breakdown
    agg="max"
)
# Returns: [{"deployment": "frontend", "throttle_pct": 97.1}, {"deployment": "ad", "throttle_pct": 68.9}, ...]
```

**Example 3: Time Series of Cluster Memory**
```python
metric_analysis(
    base_dir="path/to/metrics",
    object_pattern="pod/*",
    metric_names=["container_memory_usage_bytes", "...limits"],
    eval="mem_pct = ...",
    group_by="timestamp"  # Returns time series
)
# Returns: [{"timestamp": "2025-12-01 21:16:24", "mem_pct": 23.1}, {"timestamp": "...", "mem_pct": 24.2}, ...]
```

**Key Points:**
- **Metric names with special chars are AUTO-SANITIZED** (`:` → `_` in eval)
- `group_by='deployment'` → per-object analysis, auto-extracts deployment from pod names
- `group_by='timestamp'` → time series
- No `group_by` + `agg='max'` → cluster-wide aggregation

**Arguments:**
- `base_dir` (Required): Directory containing metric TSV files.
- `k8_object_name` (Optional): Specific object (e.g., 'pod/my-pod'). Omit for batch queries.
- `object_pattern` (Optional): Glob pattern (e.g., 'pod/*', 'service/*'). Default: '*' (all).
- `metric_names` (Optional): List of metric names to load.
- `eval` (Optional): Pandas eval string for derived metrics.
- `group_by` (Optional): Column to group by. Special: 'deployment', 'pod_name', 'metric_name'.
- `agg` (Optional): Aggregation function (mean, sum, max, min). Default: mean.
- `start_time` / `end_time` (Optional): Time range filter.

**3. get_metric_anomalies**

Reads metrics and detects anomalies for a specific Kubernetes object.
Use this to check for CPU spikes, memory leaks, or error rate increases.

**Tip:** Use `metric_analysis` first to identify relevant metric names.

- `k8_object_name` (Required): Name of the object.
- `base_dir` (Required): Directory containing metric TSV files.
- `metric_name_filter` (Optional): Only analyze metrics matching this name/substring.
- `start_time` (Optional): Start timestamp.
- `end_time` (Optional): End timestamp.
- `raw_content` (Optional): Include raw time series data (default: true).

**4. event_analysis**

Analyzes Kubernetes events. Works like SQL: `filter → group_by → agg`.
Supports multi-column grouping and multiple aggregation types.

**Example 1: Event count by reason (find red flags)**
```python
event_analysis(events_file="...", group_by="reason")
# Returns: [{"reason": "Unhealthy", "count": 45}, {"reason": "Killing", "count": 12}, ...]
```

**Example 2: Warning events per deployment**
```python
event_analysis(events_file="...", filters={"event_kind": "Warning"}, group_by="deployment")
# Returns: [{"deployment": "frontend", "count": 5}, ...]
```

**Example 3: Multi-column group by**
```python
event_analysis(events_file="...", group_by=["namespace", "reason"])
# Returns: [{"namespace": "otel-demo", "reason": "Unhealthy", "count": 45}, ...]
```

**Example 4: First event per pod (debugging)**
```python
event_analysis(events_file="...", group_by="object_name", agg="first")
# Returns: First event for each object
```

**Aggregation Types:**
- `count` (default): Count events per group
- `first` / `last`: First or last event per group
- `nunique`: Count unique values per column
- `list`: List unique values (e.g., all reasons for a pod)

**Arguments:**
- `events_file` (Required): Path to k8s_events TSV file.
- `filters` (Optional): Column filters (e.g., `{"reason": "Unhealthy", "namespace": "otel-demo"}`).
- `group_by` (Optional): Column(s) to group by. String or list. Special: `deployment` extracts from pod names.
- `agg` (Optional): Aggregation type (`count`, `first`, `last`, `nunique`, `list`).
- `sort_by` (Optional): Column to sort by.
- `limit` (Optional): Max rows to return. **Use `0` to fetch ALL rows** (no limit).
- `offset` (Optional): Skip first N rows (pagination). Default: 0.
- `start_time` / `end_time` (Optional): Time range filter.

**Response includes pagination metadata:**
```json
{
  "total_count": 450,
  "offset": 100,
  "limit": 100,
  "returned_count": 100,
  "data": [...]
}
```

**5. get_trace_error_tree**

Analyzes distributed traces to find **critical paths with regressions**. Returns a compact, actionable output focused on what's broken.

**Key Features:**
- **Compact output**: `all_paths` shows service chains with traffic rates; `critical_paths` details only degraded paths
- **Full lineage**: Shows upstream callers (who calls this service), not just downstream
- **Threshold filtering**: Only paths exceeding error/latency thresholds are analyzed in detail
- **Per-hop metrics**: Each service in a critical path shows traffic, error rate, and latency changes
- **Root cause detection**: Identifies downstream service with highest error rate

**Example: Compare before/after an incident**
```python
get_trace_error_tree(
    trace_file="otel_traces.tsv",
    service_name="checkout",
    pivot_time="2025-12-01T21:20:00Z",
    delta_time="5m",
    error_threshold_pct=10,    # Only show if error rate changed >10%
    latency_threshold_pct=10   # Only show if latency changed >10%
)
```

**Arguments:**
- `trace_file` (Required): Path to OpenTelemetry traces TSV file.
- `service_name` (Optional): Filter to traces that CONTAIN this service (shows full lineage).
- `span_kind` (Optional): Filter spans by kind (`Client`, `Server`, `Internal`).
- `pivot_time` (Highly recommended): Timestamp for before/after comparison (ISO 8601).
- `delta_time` (Optional): Window size for comparison (default: "5m").
- `error_threshold_pct` (Optional): Only detail paths with error change > threshold (default: 10).
- `latency_threshold_pct` (Optional): Only detail paths with latency change > threshold (default: 10).

**Output Structure:**

```json
{
  "_description": {
    "overview": "Critical path analysis - only significant regressions shown in detail",
    "thresholds": {"error_rate_change_pct": 10, "latency_change_pct": 10},
    "note": "Paths not in critical_paths are healthy."
  },
  "summary": {
    "pre": {"trace_count": 205, "error_rate_pct": 8.08, "latency_p99_ms": 104786},
    "post": {"trace_count": 526, "error_rate_pct": 16.31, "latency_p99_ms": 94081},
    "delta": {"traffic_change_pct": 156.6, "error_rate_change_pct": 101.9}
  },
  "all_paths": [
    "load-generator(3/s) → frontend-proxy(3/s) → frontend(6/s) → checkout(13/s) (CRITICAL)",
    "load-generator(3/s) → frontend-proxy(3/s) → frontend(6/s) → checkout(13/s) → payment(1/s) (CRITICAL)",
    "load-generator(3/s) → frontend-proxy(3/s) → frontend(6/s) → checkout(13/s) → cart(6/s) (WARNING)",
    "load-generator(3/s) → frontend-proxy(3/s) → frontend(6/s) → checkout(13/s) → currency(2/s)"
  ],
  "critical_paths": [
    {
      "path": "load-generator → frontend-proxy → frontend → checkout",
      "severity": "CRITICAL",
      "hops": [
        {"service": "load-generator", "traffic": "1/s → 3/s", "error_rate": "43% → 49%", "latency_p99": "2.3m → 2.0m"},
        {"service": "frontend-proxy", "traffic": "0.89/s → 3/s", "error_rate": "51% → 58%", "latency_p99": "15.2s → 15.2s"},
        {"service": "frontend", "traffic": "2/s → 6/s", "error_rate": "15% → 41%", "latency_p99": "1.7m → 1.9m"},
        {"service": "checkout", "traffic": "5/s → 13/s", "error_rate": "3% → 14%", "latency_p99": "1.4m → 1.5m"}
      ],
      "root_cause_suspect": {"service": "frontend-proxy", "reason": "58% error rate"},
      "sample_errors": ["connection timeout"]
    }
  ]
}
```

**Reading the output:**
1. Scan `all_paths` - paths marked (CRITICAL)/(WARNING) need attention
2. Read `critical_paths` - each hop shows `pre → post` metrics to trace where degradation starts
3. Check `root_cause_suspect` - the downstream service most likely causing the issue

**6. alert_summary** ⭐ (Start here for alerts)

Provides a high-level overview of all alerts in a scenario. Use this FIRST to understand what's happening before diving into specific alerts with `alert_analysis`.

**Returns for each unique alert:**
- `alertname`: Type of alert (e.g., RequestErrorRate, TargetDown)
- `entity`: Affected service/pod/component
- `severity`: warning, critical, none
- `state`: firing, pending
- `first_seen` / `last_seen`: Time range when alert was observed
- `duration_min`: How long the alert has been active
- `occurrences`: How many times alert appeared in snapshots

**Example 1: Get alert overview**
```python
alert_summary(base_dir="Scenario-3")
# Returns: 
# [
#   {"alertname": "RequestErrorRate", "entity": "frontend", "severity": "warning", 
#    "state": "firing", "first_seen": "2025-11-19 03:00:00", "last_seen": "2025-11-19 03:04:20",
#    "duration_min": 4.3, "occurrences": 7},
#   {"alertname": "TargetDown", "entity": "otel-collector", "severity": "warning",
#    "duration_min": 4.4, "occurrences": 6},
#   ...
# ]
```

**Example 2: Only firing alerts with long duration**
```python
alert_summary(base_dir="Scenario-3", state_filter="firing", min_duration_min=5)
# Returns only alerts that have been firing for 5+ minutes
```

**Arguments:**
- `base_dir` (Required): Scenario directory OR alerts subdirectory (auto-detects)
- `state_filter` (Optional): Filter by state ('firing', 'pending')
- `min_duration_min` (Optional): Minimum duration in minutes
- `limit` (Optional): Max alerts to return (default: 50)

**7. alert_analysis**

Analyzes alerts. Works like SQL: `filter → group_by → agg`.
Computes `duration_active` (how long each alert has been firing).

**Example 1: Alert count by type**
```python
alert_analysis(base_dir="...", group_by="alertname")
# Returns: [{"alertname": "RequestErrorRate", "count": 38}, {"alertname": "RequestLatency", "count": 15}, ...]
```

**Example 2: Firing alerts by severity**
```python
alert_analysis(base_dir="...", filters={"state": "firing"}, group_by="severity")
# Returns: [{"severity": "warning", "count": 68}, {"severity": "critical", "count": 8}]
```

**Example 3: Long-running alerts (sorted by duration)**
```python
alert_analysis(base_dir="...", filters={"state": "firing"}, sort_by="duration_active_min", limit=10)
# Returns alerts sorted by how long they've been firing
```

**Example 4: Max duration by alert type**
```python
alert_analysis(base_dir="...", group_by="alertname", agg="max")
# Returns: [{"alertname": "Watchdog", "duration_active_min": 8137.1}, ...]
```

**Column Shortcuts:**
- `alertname` → `labels.alertname`
- `severity` → `labels.severity`
- `service_name` → `labels.service_name`
- `namespace` → `labels.namespace`

**Aggregation Types:**
- `count` (default): Count alerts per group
- `first` / `last`: First or last alert per group
- `sum`, `mean`, `max`, `min`: Numeric aggregations on `value` and `duration_active_min`

**Arguments:**
- `base_dir` (Required): Directory containing alert JSON files.
- `filters` (Optional): Column filters (e.g., `{"state": "firing", "severity": "critical"}`).
- `group_by` (Optional): Column(s) to group by. String or list.
- `agg` (Optional): Aggregation type.
- `sort_by` (Optional): Column to sort by (e.g., `duration_active_min`).
- `limit` (Optional): Max rows to return. **Use `0` to fetch ALL rows** (no limit).
- `offset` (Optional): Skip first N rows (pagination). Default: 0.
- `start_time` / `end_time` (Optional): Time range filter.

**Response includes pagination metadata** (same format as event_analysis).

**8. k8s_spec_change_analysis**

Analyzes Kubernetes object spec changes over time. Detects and reports **meaningful** spec changes, filtering out timestamp-related churn (resourceVersion, managedFields, etc.).

**Use Cases:**
- Identify config drift (what changed in a deployment?)
- Track rollouts (which specs changed during an incident window?)
- Correlate incidents with changes (did a ConfigMap change just before the outage?)

**Example 1: Find all spec changes**
```python
k8s_spec_change_analysis(k8s_objects_file="k8s_objects.tsv")
# Returns entities sorted by change_count:
# {
#   "total_entities": 112,
#   "entities_with_changes": [
#     {"entity": "ConfigMap/flagd-config", "change_count": 1, "changes": [...]},
#     {"entity": "Deployment/load-generator", "change_count": 1, "changes": [...]},
#     ...
#   ]
# }
```

**Example 2: Changes to a specific deployment**
```python
k8s_spec_change_analysis(
    k8s_objects_file="k8s_objects.tsv",
    k8_object_name="Deployment/cart"
)
# Returns only changes for the cart deployment
```

**Example 3: Changes during incident window**
```python
k8s_spec_change_analysis(
    k8s_objects_file="k8s_objects.tsv",
    start_time="2025-12-01T21:20:00Z",
    end_time="2025-12-01T21:30:00Z"
)
# Returns only spec changes within the time window
```

**Example 4: Pagination for large datasets**
```python
k8s_spec_change_analysis(
    k8s_objects_file="k8s_objects.tsv",
    limit=10,        # Return top 10 entities
    offset=0         # Skip 0 entities
)
```

**Output Format:**
```json
{
  "reference_spec_file": "k8s_objects.tsv",
  "input_format": "processed",
  "total_entities": 112,
  "returned_count": 4,
  "entities_with_changes": [
    {
      "entity": "Deployment/load-generator",
      "kind": "Deployment",
      "name": "load-generator",
      "first_timestamp": "2025-12-01 21:20:45",
      "last_timestamp": "2025-12-01 21:25:44",
      "observation_count": 2,
      "duration_sec": 298.59,
      "change_count": 1,
      "reference_spec": {
        "timestamp": "2025-12-01 21:20:45",
        "spec": {"apiVersion": "apps/v1", "kind": "Deployment"}
      },
      "changes": [
        {
          "timestamp": "2025-12-01 21:25:44",
          "from_timestamp": "2025-12-01 21:20:45",
          "changes_truncated": false,
          "change_item_count": 1,
          "change_item_total": 1,
          "changes": [
            {"path": "spec.template.metadata.annotations.kubectl.kubernetes.io/restartedAt", "type": "added", "new": "2025-12-01T21:22:22Z"}
          ]
        }
      ],
      "change_items": [
        {"timestamp": "2025-12-01 21:25:44", "from_timestamp": "2025-12-01 21:20:45", "path": "spec.template.metadata.annotations.kubectl.kubernetes.io/restartedAt", "type": "added", "new": "2025-12-01T21:22:22Z"}
      ],
      "change_item_count": 1
    }
  ]
}
```

**Filtered Fields (churn prevention):**
The tool automatically filters out these fields to avoid noisy "changes":
- `resourceVersion`, `managedFields`, `generation`, `uid`
- `creationTimestamp`, `lastTransitionTime`, `lastUpdateTime`
- `status`, `containerStatuses`, `conditions`, `podIP`, `hostIP`
- Annotations: `endpoints.kubernetes.io/last-change-trigger-time`, `kubectl.kubernetes.io/last-applied-configuration`

**Arguments:**
- `k8s_objects_file` (Required): Path to k8s_objects TSV file.
- `k8_object_name` (Optional): Filter by specific object (`Kind/name` format). For namespaced objects, the tool also emits entity IDs as `Kind/namespace/name`.
- `start_time` / `end_time` (Optional): Time range filter.
- `max_changes_per_diff` (Optional): Max change items to return per diff window. If omitted, returns all.
- `include_reference_spec` (Optional): Include the baseline spec used for diffing. Default: true.
- `include_flat_change_items` (Optional): Include `change_items` flat list. Default: true.
- `time_basis` (Optional): `"observation"` or `"effective_update"`. Controls what timestamp is used for time window filtering.
  - `"observation"` uses OTEL/log record time (`TimestampTime` / `timestamp` column).
  - `"effective_update"` uses a best-effort update time extracted from the object (`max(managedFields[].time, restartedAt, ...)`) so changes can be attributed to the window even if they were *observed later* by periodic snapshots.
  - **Default:** `"effective_update"` for raw OTEL inputs, `"observation"` for processed snapshot inputs.
- `lifecycle_inference` (Optional): `"none"` or `"window"`. **Default:** `"none"` for raw OTEL `k8sobjectsreceiver` input (to avoid noisy inferred adds/removes), `"window"` for processed snapshots.
- `lifecycle_scope` (Optional): `"global"` or `"per_kind"`. When lifecycle inference is enabled, controls whether add/remove inference uses the global dataset window or per-kind windows. **Default:** `"per_kind"` for raw OTEL input, `"global"` for processed snapshots.
- `removal_grace_period_sec` (Optional): Hysteresis for inferred removals (requires the entity to be absent for at least this many seconds). **Default:** `300` for raw OTEL when lifecycle inference is enabled; otherwise `0`.
- `removal_min_cycles` (Optional): Hysteresis for inferred removals (requires the entity to be absent across at least this many subsequent observation cycles). **Default:** `2` for raw OTEL when lifecycle inference is enabled; otherwise `0`.
- `limit` (Optional): Max entities to return (pagination).
- `offset` (Optional): Skip first N entities (pagination). Default: 0.
- `include_no_change` (Optional): Include entities with no spec changes. Default: false.

**9. get_k8_spec**

Retrieves the Kubernetes spec for a specific resource. Returns the full spec from the k8s_objects TSV file.

**Identifier Formats (all tools support these):**
- `namespace/kind/name` - **PREFERRED** (e.g., `otel-demo/Service/cart`) - unambiguous, returns exact match
- `kind/name` - **DISCOURAGED** (e.g., `Service/cart`) - ambiguous, returns ALL matches across namespaces
- `name` - **DISCOURAGED** (e.g., `cart`) - most ambiguous, returns ALL matches across kinds and namespaces

**Use Cases:**
- Inspect current resource configuration
- Examine deployment specs, service definitions, configmaps
- Debug resource configurations during incidents
- Compare expected vs actual resource definitions

**Example 1: Get spec with precise identifier (PREFERRED)**
```python
get_k8_spec(
    k8s_objects_file="k8s_objects_raw.tsv",
    k8_object_name="otel-demo/Deployment/cart"  # namespace/kind/name
)
# Returns exact match:
# {
#   "found": true,
#   "identifier_format": "namespace/kind/name",
#   "entity_id": "otel-demo/Deployment/cart",
#   "kind": "Deployment",
#   "namespace": "otel-demo",
#   "name": "cart",
#   "spec": {...}
# }
```

**Example 2: Ambiguous identifier (returns all matches)**
```python
get_k8_spec(
    k8s_objects_file="k8s_objects_raw.tsv",
    k8_object_name="cart"  # name only - ambiguous
)
# Returns ALL resources named 'cart':
# {
#   "found": true,
#   "identifier_format": "name",
#   "warning": "Format 'name' is highly ambiguous...",
#   "entity_count": 3,
#   "entities": {
#     "otel-demo/Deployment/cart": {...},
#     "otel-demo/Service/cart": {...},
#     "otel-demo/Endpoints/cart": {...}
#   }
# }
```

**Example 3: Get all observations over time**
```python
get_k8_spec(
    k8s_objects_file="k8s_objects_raw.tsv",
    k8_object_name="otel-demo/ConfigMap/flagd-config",
    return_all_observations=True
)
# Returns all observations of the ConfigMap, useful for seeing how it evolved
```

**Output Format (single entity):**
```json
{
  "k8s_objects_file": "k8s_objects_raw.tsv",
  "k8_object_name": "otel-demo/Deployment/cart",
  "identifier_format": "namespace/kind/name",
  "input_format": "processed",
  "found": true,
  "observation_count": 3,
  "timestamp": "2025-12-01T21:25:44Z",
  "entity_id": "otel-demo/Deployment/cart",
  "kind": "Deployment",
  "namespace": "otel-demo",
  "name": "cart",
  "spec": {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "cart", "namespace": "otel-demo", ...},
    "spec": {"replicas": 1, "template": {...}}
  }
}
```

**Arguments:**
- `k8s_objects_file` (Required): Path to k8s_objects TSV file (e.g., `k8s_objects_raw.tsv`).
- `k8_object_name` (Required): K8s resource identifier. Formats: `namespace/kind/name` (PREFERRED), `kind/name`, or `name`.
- `return_all_observations` (Optional): If true, return all observations over time instead of just the latest. Default: false.
- `include_metadata` (Optional): If true, include full metadata in response. Default: true.

**10. get_context_contract** ⭐ (Aggregation Tool)

Aggregates **full operational context** for a K8s entity by calling multiple analysis tools internally. This is the recommended starting point for incident investigation.

**What it returns:**
1. **Dependencies** (via `topology_analysis`)
2. **Events** for the entity (via `event_analysis`)
3. **Alerts** related to the entity (via `alert_analysis`)
4. **Trace error tree** (via `get_trace_error_tree`)
5. **Metric anomalies** (via `get_metric_anomalies`)
6. **K8s object spec** (via `get_k8_spec` - latest spec for the entity)
7. **Spec changes** (via `k8s_spec_change_analysis`)
8. **Dependency context** (events + spec changes for each dependency)

**Dependency Traversal Strategy:**

The tool discovers dependencies using a **"1 transitive hop"** strategy:

```
Entity (e.g., Service/ad)
├── Direct deps (hop 0): calls, depends_on from entity + its backing pods
│   └── Service/flagd, Service/otel-collector, ConfigMap/kube-root-ca.crt, ...
│
└── Transitive deps (hop 1): dependencies OF the direct deps
    └── ConfigMap/flagd-config (because flagd depends on it)
```

- **Only functional edges** (`calls`, `depends_on`) are followed - NOT `contains`
- **Pod-level dependencies** are included (e.g., Pod/ad → Service/flagd)
- **ConfigMaps, Secrets, ServiceAccounts** are captured as infrastructure dependencies
- This ensures you see `ConfigMap/flagd-config` when investigating `Service/ad`

The output includes a `dependency_breakdown` showing direct vs transitive:
```json
{
  "dependency_breakdown": {
    "direct": ["Service/flagd", "Service/otel-collector", "ConfigMap/kube-root-ca.crt"],
    "transitive": ["ConfigMap/flagd-config", "ConfigMap/otel-collector"]
  }
}
```

**Pagination:**
- **Page 1**: Main entity context (all 7 sections above)
- **Page 2+**: Dependency context (events + spec changes for `deps_per_page` dependencies)

**Example 1: Get full context for a service**
```python
get_context_contract(
    k8_object="Deployment/cart",
    snapshot_dir="/path/to/snapshot",  # Contains k8s_events*.tsv, k8s_objects*.tsv, etc.
    topology_file="/path/to/topology.json",  # Optional
    page=1
)
# Returns:
# {
#   "entity": "Deployment/cart",
#   "pagination": {"current_page": 1, "total_pages": 3, "total_dependencies": 5},
#   "events": {"count": 12, "items": [...]},
#   "alerts": {"total_alerts": 45, "related_to_entity": 3},
#   "trace_errors": {...},
#   "metric_anomalies": {...},
#   "k8s_object_definition": {...},
#   "spec_changes": {...},
#   "dependencies": ["valkey-cart", "postgresql"]
# }
```

**Example 2: With time window**
```python
get_context_contract(
    k8_object="Service/frontend",
    snapshot_dir="/path/to/snapshot",
    start_time="2025-12-01T21:20:00Z",
    end_time="2025-12-01T21:30:00Z",
    page=1
)
# Returns context filtered to the incident window
```

**Example 3: Get dependency context (page 2)**
```python
get_context_contract(
    k8_object="Deployment/cart",
    snapshot_dir="/path/to/snapshot",
    page=2,         # Page 2 = first batch of dependencies
    deps_per_page=3  # 3 dependencies per page
)
# Returns:
# {
#   "entity": "Deployment/cart",
#   "context_type": "dependencies",
#   "dependencies_on_page": ["valkey-cart", "postgresql", "kafka"],
#   "dependency_context": {
#     "valkey-cart": {"events": {...}, "spec_changes": {...}},
#     "postgresql": {"events": {...}, "spec_changes": {...}},
#     "kafka": {"events": {...}, "spec_changes": {...}}
#   }
# }
```

**Snapshot Directory Structure:**
The tool automatically finds these files in `snapshot_dir`:
```
snapshot_dir/
├── k8s_events_*.tsv      # Events file
├── k8s_objects_*.tsv     # Objects file
├── otel_traces.tsv       # Traces file
├── alerts/               # Alert JSON files
│   ├── alerts_at_*.json
│   └── ...
└── metrics/              # Metric TSV files
    ├── pod_*.tsv
    └── service_*.tsv
```

**Arguments:**
- `k8_object` (Required): K8s object in `Kind/name` format (e.g., `Deployment/cart`).
- `snapshot_dir` (Required): Path to snapshot directory with data files.
- `topology_file` (Optional): Path to topology JSON. If not provided, looks for `operational_topology.json` in snapshot_dir.
- `start_time` / `end_time` (Optional): Time range filter.
- `page` (Optional): Page number. Page 1 = main entity, Page 2+ = dependencies. Default: 1.
- `deps_per_page` (Optional): Dependencies per page (for page >= 2). Default: 3.

---

## Testing Tools Without Zero

You can test the tools directly using Python without running the Zero agent.

### Method 1: Command-Line Interface

The `offline_incident_analysis` tools module has a built-in CLI with subcommands for each tool:

```bash
# List available tools
python -m sre_tools.offline_incident_analysis.tools --list

# Get help for a specific tool
python -m sre_tools.offline_incident_analysis.tools build_topology --help

# Run build_topology
python -m sre_tools.offline_incident_analysis.tools build_topology \
  --arch-file /path/to/app/arch.json \
  --k8s-objects-file /path/to/k8s_objects_otel-demo_chaos-mesh.tsv \
  --output-file /tmp/topology.json
```

Example with actual scenario data:

```bash
python -m sre_tools.offline_incident_analysis.tools build_topology \
  --arch-file workspace/shared/application_architecture.json \
  --k8s-objects-file ./ITBench-Lite/snapshots/sre/v0.2-*/Scenario-105/k8s_objects_otel-demo_chaos-mesh.tsv \
  --output-file /tmp/topology.json
```

### Method 2: Python API

Import and call the function directly in Python:

```python
from sre_tools.offline_incident_analysis.tools import build_topology_standalone

# Build topology
topology = build_topology_standalone(
    arch_file="app/arch.json",
    k8s_objects_file="k8s_objects_otel-demo_chaos-mesh.tsv",
    output_file="topology.json"
)

print(f"Built topology with {len(topology['nodes'])} nodes and {len(topology['edges'])} edges")

# Inspect the topology
for node in topology["nodes"][:5]:
    print(f"  Node: {node['id']} ({node['kind']})")
```

### Method 3: MCP Inspector

Test the MCP server with the official MCP inspector:

```bash
# Install mcp-inspector
npm install -g @modelcontextprotocol/inspector

# Run the MCP server with inspector
npx @modelcontextprotocol/inspector python -m sre_tools.offline_incident_analysis
```

This opens a web UI where you can:
- See available tools
- Call tools with arguments
- Inspect responses

---

### 2. `kubernetes` - Kubernetes MCP Server

**Type:** External MCP Server via npx (stdio)  
**Source:** [github.com/containers/kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server)

A full-featured Kubernetes MCP server for live cluster interaction.

#### Tools Provided

| Category | Tools |
|----------|-------|
| **Pods** | `pod_list`, `pod_get`, `pod_logs`, `pod_run`, `pod_delete`, `pod_exec` |
| **Deployments** | `deployment_list`, `deployment_get`, `deployment_create`, `deployment_update`, `deployment_delete` |
| **Services** | `service_list`, `service_get`, `service_create`, `service_delete` |
| **ConfigMaps/Secrets** | `configmap_*`, `secret_*` |
| **Events** | `events_get`, `workload_logs` |
| **Namespaces** | `namespace_list`, `namespace_create`, `namespace_delete` |
| **Kiali** | Service mesh topology, traces, metrics (if Kiali installed) |
| **KubeVirt** | VM management (if KubeVirt installed) |
| **Helm** | Chart operations |

#### Prerequisites

- **Node.js** (v18+) - for running via npx
- **kubectl** - configured with cluster access
- **KUBECONFIG** - environment variable set (or default `~/.kube/config`)

#### Installation Options

**Option A: No installation (via npx)**
```bash
# The tool runs automatically via npx - no pre-installation needed
python -m zero --session-dir /tmp/session --tools kubernetes
```

**Option B: Global installation (faster startup)**
```bash
# Install globally
npm install -g kubernetes-mcp-server

# Then update zero/zero-config/config.toml:
# [mcp_servers.kubernetes]
# command = "kubernetes-mcp-server"
# args = []
```

#### Usage

```bash
# Ensure kubectl is configured
export KUBECONFIG=/path/to/kubeconfig

# Enable kubernetes in zero/zero-config/config.toml then run
python -m zero --workspace /tmp/work --read-only-dir /path/to/scenario
```

---

## Adding External MCP Servers

You can add additional MCP servers (HTTP or stdio-based) to Zero's configuration.

### Example: Datadog Integration

Add to `zero/zero-config/config.toml`:

```toml
[mcp_servers.datadog]
command = "datadog-mcp-server"
args = []

[mcp_servers.datadog.env]
DATADOG_API_KEY = "your-api-key"
```

### Example: Custom HTTP MCP Server

```toml
[mcp_servers.custom]
type = "http"
url = "https://your-server.com/mcp"

[mcp_servers.custom.env]
API_TOKEN = "your-token"
```

---

## Configuration

### MCP Server Configuration

The `offline_incident_analysis` MCP server is configured in Zero's `config.toml`:

```toml
[mcp_servers.offline_incident_analysis]
command = "python"
args = ["-m", "sre_tools.offline_incident_analysis"]

[mcp_servers.offline_incident_analysis.env]
PYTHONPATH = "."
```

### Tool Declaration

Tools are declared in code using the MCP SDK. See [sre_tools/offline_incident_analysis/tools.py](sre_tools/offline_incident_analysis/tools.py) for implementation.

Each tool is defined with:
- **name**: Unique identifier (e.g., `build_topology`)
- **description**: Human-readable explanation
- **inputSchema**: JSON Schema defining input parameters

Example:
```python
from mcp.server import Server
from mcp.types import Tool

server = Server("offline_incident_analysis")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="build_topology",
            description="Build operational topology...",
            inputSchema={
                "type": "object",
                "properties": {
                    "arch_file": {"type": "string"},
                    # ... more properties
                },
                "required": ["arch_file"]
            }
        )
    ]
```

---

## Creating New Tools

### Option A: Add to Existing offline_incident_analysis (Recommended)

The easiest way to add a new tool is to extend `sre_tools/cli/offline_incident_analysis/tools.py`:

**Step 1: Add the standalone function**

```python
def my_new_tool_standalone(input_file: str, output_file: str) -> dict[str, Any]:
    """Process input and write output (for direct Python testing).
    
    Args:
        input_file: Path to input file
        output_file: Path to write output
        
    Returns:
        Result dictionary
    """
    # Your implementation here
    result = {"status": "ok", "data": [...]}
    
    Path(output_file).write_text(json.dumps(result, indent=2))
    return result
```

**Step 2: Add the MCP tool definition** (in `list_tools()`)

```python
Tool(
    name="my_new_tool",
    description="What it does",
    inputSchema={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Path to input"},
            "output_file": {"type": "string", "description": "Path to output"}
        },
        "required": ["input_file", "output_file"]
    }
),
```

**Step 3: Add the MCP handler** (in `call_tool()`)

```python
elif name == "my_new_tool":
    return await _my_new_tool(arguments)
```

```python
async def _my_new_tool(args: dict[str, Any]) -> list[TextContent]:
    input_file = args.get("input_file", "")
    output_file = args.get("output_file", "")
    
    if not output_file:
        return [TextContent(type="text", text="Error: output_file is required")]
    
    try:
        result = my_new_tool_standalone(input_file, output_file)
        return [TextContent(type="text", text=f"Done. Output: {output_file}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]
```

**Step 4: Add CLI subcommand** (in `main()`)

```python
# Add CLI handler
def _cli_my_new_tool(args) -> int:
    try:
        result = my_new_tool_standalone(args.input_file, args.output_file)
        print(f"✓ Output written to {args.output_file}")
        return 0
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

# Add subparser in main()
my_tool_parser = subparsers.add_parser(
    "my_new_tool",
    help="What it does"
)
my_tool_parser.add_argument("--input-file", "-i", required=True, help="Input file")
my_tool_parser.add_argument("--output-file", "-o", required=True, help="Output file")
my_tool_parser.set_defaults(func=_cli_my_new_tool)
```

**Step 5: Update the `--list` output**

```python
if args.list:
    print("Available tools:")
    print()
    print("  build_topology  - Build operational topology from architecture and K8s objects")
    print("  my_new_tool     - What it does")  # Add this line
    ...
```

Now you can use it via:
- **MCP**: Enabled automatically when `--tools offline_incident_analysis` is used
- **CLI**: `python -m sre_tools.offline_incident_analysis.tools my_new_tool --input-file ... --output-file ...`
- **Python**: `from sre_tools.offline_incident_analysis.tools import my_new_tool_standalone`

---

### Option B: Create a New MCP Server

For a completely separate tool category, create a new MCP server:

1. Create a new directory under `sre_tools/`:

```
sre_tools/my_server/
├── __init__.py
├── __main__.py
└── tools.py
```

2. Implement the MCP server (`__main__.py`):

```python
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from .tools import register_tools

async def run_server():
    app = Server("my_server")
    register_tools(app)
    # IMPORTANT: stdio_server() returns an async context manager
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

def main():
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import sys
        print(f"Error starting MCP server: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

3. Define tools (`tools.py`) - follow the pattern in `offline_incident_analysis/tools.py`

4. Add to `zero/zero-config/config.toml`:

```toml
[mcp_servers.my_server]
command = "python"
args = ["-m", "sre_tools.my_server"]

[mcp_servers.my_server.env]
PYTHONPATH = "."
```

## IMPORTANT NOTE

**MCP Server Implementation:**
The `stdio_server()` function from the `mcp` library is an **async context manager**, not a coroutine.
Do NOT call it like this:
```python
# WRONG - will crash with ValueError
asyncio.run(stdio_server(app))
```

Always use this pattern:
```python
# CORRECT
async def run():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
```

This applies to all Python-based MCP servers in this project.

---

## Troubleshooting

### MCP server not starting

Check that the server is properly configured in `zero/zero-config/config.toml` and that the command/args are correct.

### kubernetes-mcp-server fails to start

1. Ensure Node.js is installed: `node --version`
2. Ensure kubectl is configured: `kubectl cluster-info`
3. Check KUBECONFIG is set: `echo $KUBECONFIG`

### MCP server times out

Check server logs and ensure the server is responding to MCP protocol requests. You can test the server independently using the MCP inspector (see "Method 3: MCP Inspector" above).



# codex

```bash
# Using $PWD (run from project root)
codex --config 'mcp_servers.offline_incident_analysis.command="python3"' \
      --config 'mcp_servers.offline_incident_analysis.args=["-m", "sre_tools.offline_incident_analysis"]' \
      --config "mcp_servers.offline_incident_analysis.env={\"PYTHONPATH\":\"$PWD\"}"

# Or let Python find it (if package is installed)
codex --config 'mcp_servers.offline_incident_analysis.command="python3"' \
      --config 'mcp_servers.offline_incident_analysis.args=["-m", "sre_tools.offline_incident_analysis"]'

# Or with explicit path (update to your installation)
codex --config 'mcp_servers.offline_incident_analysis.command="/usr/bin/python3"' \
      --config 'mcp_servers.offline_incident_analysis.args=["-m", "sre_tools.offline_incident_analysis"]' \
      --config 'mcp_servers.offline_incident_analysis.env={"PYTHONPATH":"/path/to/ITBench-SRE-Agent"}'
```

---

## Code Structure

The `offline_incident_analysis` module is organized into domain-specific packages:

- `shared/` - Common utilities (parsers, filters, formatters, K8s utils, time utils)
- `topology/` - Topology building and analysis
- `metrics/` - Metric analysis and anomaly detection
- `events/` - K8s event analysis
- `logs/` - Log analysis with Drain3
- `traces/` - Distributed trace analysis
- `alerts/` - Alert analysis and summarization
- `k8s_specs/` - K8s spec change tracking and retrieval
- `context/` - Context aggregation across data sources

