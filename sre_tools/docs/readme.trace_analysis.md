# Trace Analysis Tool Architecture

This document explains the architecture and design of the `get_trace_error_tree` tool, which analyzes OpenTelemetry distributed traces to help identify the root cause of errors and latency issues in microservices.

## Overview

The trace analysis tool transforms raw span data into a **compact, actionable output** focused on critical paths with regressions. It's designed for SRE incident investigation, providing:

- **Critical path focus**: Only paths exceeding thresholds are analyzed in detail
- **Full lineage**: Shows upstream callers, not just downstream dependencies
- **Per-hop metrics**: Traffic, error rate, and latency changes at each service
- **Root cause detection**: Identifies downstream service with highest error rate
- **Compact paths**: Service chains with traffic rates (e.g., `frontend(10/s) → checkout(8/s)`)

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Input: TSV File                                 │
│  timestamp | trace_id | span_id | parent_span_id | service_name | span_kind │
│  status_code | status_message | duration_ms | ...                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Step 1: Parse & Group                                │
│                                                                              │
│  Group spans by trace_id to reconstruct distributed transactions            │
│  Build FULL trace trees using ALL spans (preserves lineage)                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Step 2: Apply Filters                                   │
│                                                                              │
│  service_name filter:                                                        │
│    Keep traces where ANY span.service_name == target                        │
│    (keeps full lineage - upstream callers included!)                        │
│                                                                              │
│  span_kind filter (optional):                                                │
│    Filter spans for stats but keep tree structure                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Step 3: Categorize by Time Window                       │
│                                                                              │
│  Assign each span to pre or post window based on timestamp:                 │
│    pre_span_ids = spans where timestamp in [pivot - delta, pivot)           │
│    post_span_ids = spans where timestamp in [pivot, pivot + delta]          │
│                                                                              │
│  Tree structure uses ALL spans; stats computed per window                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Step 4: Aggregate by Service Chain                        │
│                                                                              │
│  Collapse paths to unique service chains:                                   │
│    "load-generator → frontend → checkout → payment"                         │
│                                                                              │
│  Aggregate pre/post stats per service in chain                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Step 5: Classify Severity                                   │
│                                                                              │
│  For each service chain, check thresholds:                                  │
│    - CRITICAL: error_change > 50% or latency_change > 100%                  │
│    - WARNING: error_change > threshold or latency_change > threshold        │
│    - NEW: path only exists in post window                                   │
│    - DISAPPEARED: path only exists in pre window                            │
│    - Healthy: changes below thresholds (not detailed)                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Step 6: Build Output                                        │
│                                                                              │
│  all_paths: Service chains with traffic rates and status                    │
│    "load-generator(3/s) → frontend(6/s) → checkout(13/s) (CRITICAL)"       │
│                                                                              │
│  critical_paths: Detailed hops for paths exceeding thresholds               │
│    Each hop shows: traffic, error_rate, latency_p99 (pre → post)            │
│                                                                              │
│  Delta (percentage change):                                                  │
│    - error_rate_change_pct                                                  │
│    - latency_p50/p90/p99_change_pct                                         │
│    OR                                                                        │
│    - {status: "NEW_PATH"} or {status: "DISAPPEARED"}                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 7: Build Nested Tree                                │
│                                                                              │
│  Convert flat path stats to nested JSON tree with inline pre/post/delta:   │
│                                                                              │
│  {                                                                           │
│    "name": "frontend: /checkout",                                           │
│    "stats": {                                                                │
│      "pre": {"count": 100, "error_rate_pct": 5.0, "latency_ms": {...}},     │
│      "post": {"count": 150, "error_rate_pct": 20.0, "latency_ms": {...}},   │
│      "delta": {"error_rate_change_pct": 300.0, ...}                         │
│    },                                                                        │
│    "errors": ["timeout waiting for response"],                              │
│    "children": [...]                                                         │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Output: JSON Response                                 │
│                                                                              │
│  {                                                                           │
│    "_description": { /* explains all fields */ },                           │
│    "warnings": [...],  /* if pivot_time not provided */                     │
│    "summary": {                                                              │
│      "pre": {...},                                                          │
│      "post": {...},                                                          │
│      "delta": {"error_rate_change_pct": 500.0, ...}                         │
│    },                                                                        │
│    "tree": [  /* unified tree with pre/post/delta per node */  ],           │
│    "filters_applied": {...}                                                  │
│  }                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Trace vs Span

- **Trace**: A complete distributed transaction, identified by `trace_id`. Contains multiple spans.
- **Span**: A single operation within a trace, identified by `span_id`. Has a parent (`parent_span_id`) except for root spans.

### Path Signature

A path signature represents a unique call chain through the system:

```
"load-generator: user_checkout" -> "frontend: /api/checkout" -> "checkout: grpc/PlaceOrder" -> "payment: ProcessPayment"
```

By aggregating statistics per path, we can identify:
- Which paths have high error rates
- Which paths have high latency
- How the same service behaves in different call contexts

### Service Name Filter

The `service_name` filter finds **traces that contain** the specified service:

```python
# Keep trace if ANY span in the trace has service_name == target
filtered_traces = {
    tid: spans for tid, spans in spans_by_trace.items()
    if any(s.get("service_name") == service_name for s in spans)
}
```

This is different from filtering individual spans - we keep the entire trace to preserve context.

### Span Kind Filter

OpenTelemetry defines three span kinds:
- **Client**: Outgoing RPC/HTTP call
- **Server**: Incoming RPC/HTTP request being handled
- **Internal**: Internal operation (not a network call)

Filtering by `span_kind="Server"` shows only server-side processing, useful for understanding where time is spent handling requests.

## Unified Tree Structure

The key innovation is the **unified tree** format where each node contains pre/post/delta inline:

```json
{
  "name": "checkout: grpc/PlaceOrder",
  "stats": {
    "pre": {
      "count": 100,
      "error_rate_pct": 2.0,
      "latency_ms": {"p50": 30, "p90": 60, "p99": 100}
    },
    "post": {
      "count": 150,
      "error_rate_pct": 18.0,
      "latency_ms": {"p50": 80, "p90": 400, "p99": 900}
    },
    "delta": {
      "error_rate_change_pct": 800.0,
      "latency_p50_change_pct": 166.7,
      "latency_p90_change_pct": 566.7,
      "latency_p99_change_pct": 800.0
    }
  },
  "errors": ["connection timeout", "redis unavailable"],
  "children": [...]
}
```

### Change Detection

Paths that only exist in one window are marked:

**NEW_PATH** - appeared after the incident (potential new error handling, fallback, or feature):
```json
{
  "name": "checkout: grpc/FallbackPayment",
  "stats": {
    "pre": null,
    "post": {"count": 50, "error_rate_pct": 80.0, ...},
    "delta": {"status": "NEW_PATH"}
  }
}
```

**DISAPPEARED** - stopped being called (potential dependency failure):
```json
{
  "name": "cart: HMSET",
  "stats": {
    "pre": {"count": 100, "error_rate_pct": 0.0, ...},
    "post": null,
    "delta": {"status": "DISAPPEARED"}
  }
}
```

## Pre/Post Comparison

When `pivot_time` is provided, the tool splits data into two windows:

```
Timeline:
[-------- pre window --------][-------- post window --------]
                              ^
                         pivot_time
```

The summary provides aggregate metrics:

| Metric | Description |
|--------|-------------|
| `traffic_rate_per_sec` | Traces per second (throughput) |
| `error_rate_pct` | Percentage of spans with errors |
| `latency_ms.p50/p90/p99` | Latency percentiles |

The `delta` section shows percentage change:

```json
{
  "delta": {
    "traffic_rate_change_pct": 157.4,   // 157% more traffic
    "error_rate_change_pct": 101.9,     // 2x increase in errors
    "latency_p99_change_pct": -10.2     // p99 slightly better (timeouts cutting off?)
  }
}
```

## Usage Patterns

### 1. Before/After Incident Analysis (Recommended)

When you know the incident start time:

```python
get_trace_error_tree(
    trace_file="otel_traces.tsv",
    service_name="checkout",
    pivot_time="2025-12-01T21:20:00Z",
    delta_time="10m"
)
```

### 2. Focus on a Failing Service

After identifying a problematic service from alerts:

```python
get_trace_error_tree(
    trace_file="otel_traces.tsv",
    service_name="checkout",
    pivot_time="2025-12-01T21:20:00Z"
)
```

### 3. Server-Side Focus

To understand where time is spent processing requests:

```python
get_trace_error_tree(
    trace_file="otel_traces.tsv",
    service_name="frontend",
    span_kind="Server",
    pivot_time="2025-12-01T21:20:00Z"
)
```

## Self-Documenting Output

The output includes a `_description` field explaining all fields:

```json
{
  "_description": {
    "overview": "Trace analysis comparing two time windows around a pivot point",
    "time_windows": {
      "pre": "Time window BEFORE pivot_time: [pivot_time - delta_time, pivot_time)",
      "post": "Time window AFTER pivot_time: [pivot_time, pivot_time + delta_time]"
    },
    "summary.pre/post": {
      "trace_count": "Number of unique distributed traces",
      "traffic_rate_per_sec": "Traces per second",
      "error_rate_pct": "Percentage of spans with status_code=Error",
      "latency_ms": "Latency percentiles (p50, p90, p99)"
    },
    "tree[].stats.delta": "Percentage change, or {status: 'NEW_PATH'|'DISAPPEARED'}"
  }
}
```

## Performance Considerations

- **Large trace files**: The tool reads the entire file into memory. For very large files (>1GB), consider pre-filtering with time ranges.
- **Path explosion**: Systems with high cardinality (many unique paths) will produce large trees. Filter by `service_name` to reduce scope.
- **Percentile accuracy**: Percentiles are computed using simple sorted-index method, which is accurate for datasets >100 samples.

## Integration with Other Tools

The trace analysis tool is called by `get_context_contract` to provide trace context for a K8s entity:

```python
# get_context_contract internally calls:
trace_result = await _get_trace_error_tree({
    "trace_file": traces_file,
    "service_name": entity_service_name,
    "pivot_time": start_time
})
```

This provides a unified view of an entity's behavior including events, alerts, metrics, and traces.
