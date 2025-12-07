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

```bash
# List all available tools
python -m zero --list-tools

# Enable tools when running Zero
python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \
  --tools sre_utils \
  --tools kubernetes
```

## Available Tools

### 1. `sre_utils` - SRE Utility Functions

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
| `get_trace_error_tree` | Analyze traces and generate error tree with statistics |
| `alert_analysis` | Analyze alerts with filtering, grouping, duration tracking |

#### Usage with Zero

```bash
python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \
  --tools sre_utils
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
- `limit` (Optional): Max rows to return.
- `start_time` / `end_time` (Optional): Time range filter.

**5. get_trace_error_tree**

Analyzes traces to find error patterns. Returns a hierarchical tree of call paths aggregated by error rate and latency.

**Recommended Use:** Use this to pinpoint where a distributed transaction is failing. The tree structure makes it easy to see if a frontend error is actually caused by a deep backend service failure (e.g., "Checkout path broken -> shipping quote failure -> email service 400").

- `trace_file` (Required): Path to otel_traces TSV file.
- `service_name` (Optional): Filter by service name.
- `pivot_time` (Optional): Timestamp to compare stats before/after.
- `delta_time` (Optional): Window size (default: "5m").

**6. alert_analysis**

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
- `limit` (Optional): Max rows to return.
- `start_time` / `end_time` (Optional): Time range filter.

---

## Testing Tools Without Zero

You can test the tools directly using Python without running the Zero agent.

### Method 1: Command-Line Interface

The `sre_utils` tools module has a built-in CLI with subcommands for each tool:

```bash
# List available tools
python -m sre_tools.cli.sre_utils.tools --list

# Get help for a specific tool
python -m sre_tools.cli.sre_utils.tools build_topology --help

# Run build_topology
python -m sre_tools.cli.sre_utils.tools build_topology \
  --arch-file /path/to/app/arch.json \
  --k8s-objects-file /path/to/k8s_objects_otel-demo_chaos-mesh.tsv \
  --output-file /tmp/topology.json
```

Example with actual scenario data:

```bash
python -m sre_tools.cli.sre_utils.tools build_topology \
  --arch-file workspace/shared/application_architecture.json \
  --k8s-objects-file ./ITBench-Snapshots/snapshots/sre/v0.1-*/Scenario-105/k8s_objects_otel-demo_chaos-mesh.tsv \
  --output-file /tmp/topology.json
```

### Method 2: Python API

Import and call the function directly in Python:

```python
from sre_tools.cli.sre_utils.tools import build_topology_standalone

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
npx @modelcontextprotocol/inspector python -m sre_tools.cli.sre_utils
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

# Then update manifest.toml to use the binary directly:
# command = "kubernetes-mcp-server"
# args = []
```

#### Usage

```bash
# Ensure kubectl is configured
export KUBECONFIG=/path/to/kubeconfig

# Run with kubernetes tool enabled
python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \
  --tools kubernetes
```

---

## HTTP-Based Tools (External Services)

These tools connect to external observability platforms. Uncomment and configure in `manifest.toml` as needed.

### Datadog

```toml
[tools.datadog]
description = "Datadog observability integration"
type = "http"
url = "https://mcp.datadoghq.com/mcp"
bearer_token_env_var = "DATADOG_API_KEY"
```

**Setup:**
```bash
export DATADOG_API_KEY="your-api-key"
python -m zero --session-dir /tmp/session --tools datadog
```

### Dynatrace

```toml
[tools.dynatrace]
description = "Dynatrace monitoring integration"
type = "http"
url = "https://your-instance.dynatrace.com/mcp"
bearer_token_env_var = "DYNATRACE_API_TOKEN"
```

### Instana

```toml
[tools.instana]
description = "Instana APM integration"
type = "http"
url = "https://your-tenant.instana.io/mcp"
bearer_token_env_var = "INSTANA_API_TOKEN"
```

---

## Configuration

Tools are defined in `manifest.toml`. The manifest supports two types of MCP servers.

### Placeholders

The following placeholders are resolved at runtime:

| Placeholder | Description |
|-------------|-------------|
| `{python}` | Current Python interpreter (`sys.executable`) |
| `{workspace}` | Session directory path |
| `{sre_tools}` | Path to sre_tools package |

### stdio (Command-line) Servers

```toml
[tools.my_tool]
description = "Tool description"
type = "stdio"
command = "{python}"           # Use current Python interpreter
args = ["-m", "my_module"]
cwd = "{workspace}"            # Optional: working directory
env = { "VAR" = "value" }      # Optional: environment variables
env_vars = ["PASSTHROUGH_VAR"] # Optional: env vars to whitelist
```

**Note:** For local Python tools using `sre_tools`, PYTHONPATH is automatically configured to find the package.

### HTTP Servers

```toml
[tools.my_http_tool]
description = "HTTP tool description"
type = "http"
url = "https://api.example.com/mcp"
bearer_token_env_var = "API_KEY_ENV_VAR"
http_headers = { "X-Custom" = "value" }
env_http_headers = { "X-Dynamic" = "ENV_VAR_NAME" }
```

---

## Custom Manifest

Use a custom manifest file:

```bash
python -m zero --session-dir /tmp/session \
  --tools-manifest /path/to/custom/manifest.toml \
  --tools my_custom_tool
```

---

## Creating New Tools

### Option A: Add to Existing sre_utils (Recommended)

The easiest way to add a new tool is to extend `sre_tools/cli/sre_utils/tools.py`:

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
- **MCP**: Enabled automatically when `--tools sre_utils` is used
- **CLI**: `python -m sre_tools.cli.sre_utils.tools my_new_tool --input-file ... --output-file ...`
- **Python**: `from sre_tools.cli.sre_utils.tools import my_new_tool_standalone`

---

### Option B: Create a New MCP Server

For a completely separate tool category, create a new MCP server:

1. Create a new directory under `sre_tools/cli/`:

```
sre_tools/cli/my_server/
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

3. Define tools (`tools.py`) - follow the pattern in `sre_utils/tools.py`

4. Add to `manifest.toml`:

```toml
[tools.my_server]
description = "My custom MCP server"
type = "stdio"
command = "{python}"
args = ["-m", "sre_tools.cli.my_server"]
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

### Tool not found in manifest

```
Warning: Tool 'xyz' not found in manifest, skipping
```

Check that the tool name matches exactly in `manifest.toml`.

### kubernetes-mcp-server fails to start

1. Ensure Node.js is installed: `node --version`
2. Ensure kubectl is configured: `kubectl cluster-info`
3. Check KUBECONFIG is set: `echo $KUBECONFIG`

### MCP server times out

Increase timeout in manifest:

```toml
[tools.slow_tool]
startup_timeout_sec = 30
tool_timeout_sec = 120
```



# codex

codex --config 'mcp_servers.sre_utils.command="/usr/bin/<PYTHON>"'\
      --config 'mcp_servers.sre_utils.args=["-m", "sre_tools.cli.sre_utils"]' \
      --config 'mcp_servers.sre_utils.env={"PYTHONPATH"="/Users/saurabhjha/projects/open_source/sre_support_agent"}