# Instana Data Source Reference

## Instana APM (via Instana MCP)

The Instana MCP server provides access to comprehensive observability data through the following categories:

### Infrastructure Monitoring (infra)
- Query infrastructure resources and catalog data
- Visualize infrastructure topology
- Collect infrastructure metrics (CPU, memory, network, disk)
- Analyze infrastructure health and performance
- Monitor hosts, containers, and other infrastructure components

### Application Performance (app)
- Access application resources and catalog
- Query application metrics (response times, throughput, error rates)
- Retrieve application alerts and alert configurations
- Visualize application topology and service dependencies
- Analyze application performance and health
- Manage global alert settings

### Events
- Monitor Kubernetes events in real-time
- Track agent health and monitoring status
- Correlate events with incidents and alerts
- Filter events by namespace, severity, and type

### Website Monitoring (website)
- Access website monitoring metrics
- Query website catalog and configuration
- Analyze website performance and user experience
- Manage website monitoring settings

## Query Capabilities

**Instana MCP tools convert natural language queries into Instana API requests:**

Common query patterns:
- "Get all endpoints for the checkout service"
- "Show latest alerts for application X"
- "Query infrastructure metrics for namespace Y"
- "List all Kubernetes events in the last hour"
- "Show service topology for the otel-demo application"
- "Get error traces for the payment service"

**Key Instana Concepts:**
- **Golden Signals**: Latency, Traffic, Errors, Saturation
- **Services**: Automatically discovered application services
- **Endpoints**: API endpoints and entry points
- **Traces**: Distributed transaction traces with full context
- **Infrastructure**: Hosts, containers, pods, nodes

## Data Collection Tasks

**Query Instana** for:
- Alert data → Write to `$WORKSPACE_DIR/alerts.json`
- Application metrics → Write to `$WORKSPACE_DIR/metrics.json`
- Trace data → Write to `$WORKSPACE_DIR/traces.json`
- Infrastructure metrics → Write to `$WORKSPACE_DIR/infra_metrics.json`
- Events → Write to `$WORKSPACE_DIR/events.json`
- Service topology → Write to `$WORKSPACE_DIR/app.json`

**Investigation Starting Points:**
1. Query for selected alert or active alerts across all applications
2. Identify services with high error rates
3. Check for infrastructure anomalies
4. Review recent Kubernetes events
5. Analyze distributed traces for failing requests
