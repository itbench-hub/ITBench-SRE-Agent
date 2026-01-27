# ClickHouse Data Source Reference

## ClickHouse Schema (via ClickHouse MCP)

**Database: `default`** (or use fully-qualified names: `default.table_name`)
- `otel_demo_traces` - Distributed traces (TraceId, SpanId, ParentSpanId, StatusCode, Duration, ServiceName)
  - Filter errors: `WHERE StatusCode = 'Error'`
  - Duration in nanoseconds (convert: `/1000000` for ms)
- `otel_demo_logs` - Application logs (Timestamp, ServiceName, SeverityNumber, Body, TraceId)
  - Severity: 13-16=WARN, 17-20=ERROR, 21-24=FATAL
- `kubernetes_events` - K8s events (Timestamp, Body as JSON, ResourceAttributes map)
  - Filter: `WHERE ResourceAttributes['k8s.namespace.name'] = 'namespace'`
  - Body contains: `object.{reason, message, involvedObject.{kind, name, namespace}}`
- `kubernetes_objects_snapshot` - K8s resource state (Body as JSON, LogAttributes map)
  - Resource type: `LogAttributes['k8s.resource.name']` (e.g., 'Pod', 'Deployment')

**Database: `prometheus`** (use fully-qualified: `prometheus.table_name`)
- **Discovery pattern** for dynamic metric tables (must run first):
  ```sql
  SELECT name FROM prometheus.system.tables
  WHERE database='prometheus' AND name LIKE '.inner_id%'
  ```
  Returns tables like: `.inner_id.data.123456`, `.inner_id.tags.123456`, `.inner_id.metrics.123456`
  Use these table names in subsequent queries (replace `X` with actual ID).

- **Query pattern** - Join data and tags tables:
  ```sql
  FROM prometheus.`.inner_id.data.X` d
  JOIN prometheus.`.inner_id.tags.X` t ON d.id = t.id
  WHERE t.metric_name = 'metric_name_here'
  ```

- **Common filter patterns**:
  - By metric: `WHERE t.metric_name = 'traces_span_metrics_calls_total'`
  - By service: `WHERE t.tags['service_name'] = 'checkoutservice'`
  - By namespace: `WHERE t.tags['namespace'] = 'otel-demo'`
  - Errors only: `WHERE t.tags['status_code'] = 'STATUS_CODE_ERROR'`
  - Exclude noise: `WHERE t.tags['service_name'] NOT IN ('flagd', 'load-generator')`

- **Key metrics**:
  - `ALERTS` - Firing/pending alerts (CRITICAL: Start here to identify active issues)
  - `traces_span_metrics_calls_total` - Request/error counts
  - `traces_span_metrics_duration_milliseconds_bucket` - Latency (P95 via histogram buckets)

- **Investigation starting point** - Check for firing alerts:
  ```sql
  SELECT t.metric_name, d.timestamp, d.value, t.tags
  FROM prometheus.`.inner_id.data.X` d
  JOIN prometheus.`.inner_id.tags.X` t ON d.id = t.id
  WHERE t.metric_name = 'ALERTS'
  ORDER BY d.timestamp DESC
  LIMIT 50
  ```
  The `tags` map contains: `alertname`, `alertstate` (firing/pending), `namespace`, `pod`, `severity`, etc.

## Data Collection Tasks

**Query ClickHouse** for:
- Alert data → Write to `$WORKSPACE_DIR/alerts.json`
- Metrics data → Write to `$WORKSPACE_DIR/metrics.json`
- Trace data → Write to `$WORKSPACE_DIR/traces.json`
- Logs → Write to `$WORKSPACE_DIR/logs.json`
