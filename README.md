# ITBench SRE Agent

A modular framework for evaluating LLM agents on Site Reliability Engineering (SRE) incident diagnosis tasks using the [ITBench](https://github.com/itbench-hub/ITBench-Lite) benchmark.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ITBench SRE Framework                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐                          ┌──────────────────────────┐    │
│  │    Zero      │─────────────────────────▶│   ITBench Evaluations    │    │
│  │ Agent Runner │                          │   (LLM-as-a-Judge)       │    │
│  └──────────────┘                          └──────────────────────────┘    │
│        │                                              │                     │
│        ▼                                              ▼                     │
│  ┌──────────────┐                          ┌──────────────────────────┐    │
│  │   Codex CLI  │                          │   agent_output.json      │    │
│  │  (OpenAI)    │                          │   evaluation_results.json│    │
│  └──────────────┘                          └──────────────────────────┘    │
│        │                                                                    │
│        ▼                                                                    │
│  ┌──────────────┐                                                          │
│  │  SRE Tools   │                                                          │
│  │ (MCP Server) │                                                          │
│  └──────────────┘                                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Components

| Module | Description | Documentation |
|--------|-------------|---------------|
| **[Zero](./zero/)** | Thin wrapper around [Codex CLI](https://github.com/openai/codex) for running SRE agents | [zero/zero-config/README.md](./zero/zero-config/README.md) |
| **[ITBench Evaluations](./itbench_evaluations/)** | LLM-as-a-Judge evaluator for agent outputs | `itbench_evaluations/` |
| **[SRE Tools](./sre_tools/)** | MCP server with SRE diagnostic tools | [sre_tools/README.md](./sre_tools/README.md) |

### SRE Tools Overview

The SRE Tools module provides specialized MCP (Model Context Protocol) tools for incident investigation. These tools are automatically available to agents via the Zero runner.

**Conditional MCP Loading**: Zero automatically loads only the MCP servers required by your prompt template. Prompt templates specify their required servers using YAML frontmatter (see [Prompt Templates](#prompt-templates)).

| Tool | Description | Use Case |
|------|-------------|----------|
| **`alert_summary`** | High-level overview of all alerts | **Start here** - Get alert types, entities, duration, frequency |
| **`alert_analysis`** | Detailed alert analysis with filters/grouping | Filter by severity, group by alertname, track duration |
| **`event_analysis`** | Analyze K8s events | Find warnings, unhealthy pods, scheduling issues |
| **`metric_analysis`** | Batch metric queries with derived metrics | CPU throttling %, memory utilization across pods |
| **`get_metric_anomalies`** | Detect metric anomalies | Find CPU spikes, memory leaks, error rate increases |
| **`get_trace_error_tree`** | Analyze distributed traces | Find where transactions fail in call chain |
| **`build_topology`** | Build operational topology graph | Map service dependencies, K8s object relationships |
| **`topology_analysis`** | Analyze entity dependencies | Find upstream/downstream services, call chains |
| **`k8s_spec_change_analysis`** | Track K8s spec changes | Identify config drift, correlate incidents with changes |
| **`get_context_contract`** | Aggregate full entity context | **All-in-one**: events, alerts, traces, metrics, dependencies |

**Typical Investigation Flow:**
```
1. alert_summary → See what alerts are firing
2. get_context_contract → Get full context for alerted entity
3. topology_analysis → Understand dependencies
4. metric_analysis → Check resource metrics
5. k8s_spec_change_analysis → Look for recent changes
```

📖 **Full tool documentation**: [sre_tools/README.md](./sre_tools/README.md)

---

## Quick Start

### Prerequisites

- Python 3.12 or 3.13 (avoid 3.14)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- [Codex CLI](https://github.com/openai/codex) installed (`npm install -g @openai/codex`)
- **[Podman](https://podman.io/docs/installation) or [Docker](https://docs.docker.com/get-docker/)** (required for ClickHouse MCP server)
- API keys for your model provider (OpenRouter, Azure, etc.)

> **Note:** The ClickHouse MCP server runs via Podman/Docker container. We use [Altinity MCP](https://github.com/Altinity/altinity-mcp) (Go-based) instead of the Python `mcp-clickhouse` package to avoid dependency conflicts with `litellm[proxy]` (which requires `uvicorn<0.32.0` and `rich==13.7.1`, incompatible with mcp-clickhouse's requirements).

### Installation

```bash
# Clone the repository
git clone https://github.com/itbench-hub/ITBench-SRE-Agent.git
cd ITBench-SRE-Agent

# Install dependencies
uv sync
# or: python -m venv .venv && source .venv/bin/activate && pip install -e .

# Download benchmark scenarios from Hugging Face
# Start with a few scenarios to get started quickly (e.g., Scenario-2 and Scenario-5)
uv run huggingface-cli download \
  ibm-research/ITBench-Lite \
  --repo-type dataset \
  --include "snapshots/sre/v0.2-*/Scenario-2/**/*" \
  --include "snapshots/sre/v0.2-*/Scenario-5/**/*" \
  --local-dir ./ITBench-Lite

# Or download all scenarios if you need the full benchmark:
# uv run huggingface-cli download \
#   ibm-research/ITBench-Lite \
#   --repo-type dataset \
#   --include "snapshots/sre/v0.2-*/Scenario-*/**/*" \
#   --local-dir ./ITBench-Lite
```

### Environment Variables

**Recommended**: Use the provided `.env.tmpl` template:

```bash
# Copy template and fill in your values
cp .env.tmpl .env

# Edit .env with your API keys and configuration
# Then source it before running Zero
source .env
```

The template includes configuration for:
- **Model Provider API Keys**: OpenRouter (primary), with optional OpenAI and WatsonX
- **ClickHouse MCP Server**: Database connection for retrieving logs, metrics, traces and Kubernetes events
- **Kubernetes MCP Server**: Kubeconfig path for kubectl operations
- **Judge**: LLM-as-a-Judge evaluator configuration (uses LiteLLM proxy by default)

For detailed information about each variable, see the comments in [.env.tmpl](.env.tmpl).

---

## Running Components

### 1. Running LiteLLM Proxy (Required)

Before running agents, start the LiteLLM proxy in a separate terminal:

```bash
# Start LiteLLM proxy (runs on http://localhost:4000 by default)
uv run litellm --config litellm_config.yaml

# Or with a custom port
uv run litellm --config litellm_config.yaml --port 8080
```

Keep this terminal running while executing agent runs. The proxy provides a unified OpenAI-compatible endpoint for all configured models, using the API keys set in the environment variables above.


### 2. Run Agent Independently (Zero)

Zero is a thin wrapper around Codex CLI that handles workspace setup, prompt templating, and configuration.

```bash
# Basic run with prompt template
# Note: Use absolute paths for --read-only-dir and SNAPSHOT_DIRS should match
# The prompt is loaded from AGENTS.md (created from the template), so we pass "Begin investigation"
# Replace v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7 with your actual extracted directory name
# Workspace follows the structure: outputs/agent_outputs/<incident_id>/<trial_number>
uv run python -m zero --workspace ./outputs/agent_outputs/2/1 \
    --read-only-dir $(pwd)/ITBench-Lite/snapshots/sre/v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7/Scenario-2 \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=$(pwd)/ITBench-Lite/snapshots/sre/v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7/Scenario-2" \
    -- exec --full-auto -m "gemini-2.5-pro" "Begin investigation"

# With additional user query appended to the base prompt (trial 2 of same scenario)
uv run python -m zero --workspace ./outputs/agent_outputs/2/2 \
    --read-only-dir $(pwd)/ITBench-Lite/snapshots/sre/v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7/Scenario-2 \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=$(pwd)/ITBench-Lite/snapshots/sre/v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7/Scenario-2" \
    -- exec --full-auto -m "claude-4-5-opus-latest" \
    "Focus on the payment service alerts"

# Interactive mode (TUI) - useful for exploration and debugging
# For quick testing without saving results, you can use /tmp/work instead
uv run python -m zero --workspace ./outputs/agent_outputs/2/3 \
    --read-only-dir $(pwd)/ITBench-Lite/snapshots/sre/v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7/Scenario-2 \
    -- -m "gemini-2.5-pro"
```

📖 **Full documentation**: [zero/zero-config/README.md](./zero/zero-config/README.md)

### Prompt Templates

Prompt templates can specify which MCP servers they require using YAML frontmatter. Zero will automatically load only the specified servers.

**Example: Offline Investigation** ([react_shell_investigation.md](zero/zero-config/prompts/react_shell_investigation.md))
```markdown
---
mcp_servers:
  - offline_incident_analysis
---

**Task**: Investigate incident from OFFLINE snapshot data...
```

**Example: Online Investigation** ([react_online.md](zero/zero-config/prompts/react_online.md))
```markdown
---
mcp_servers:
  - offline_incident_analysis
  - clickhouse
  - kubernetes
---

**Task**: Investigate incident from LIVE data sources...
```

**How it works**:
1. Agent queries ClickHouse and Kubernetes to collect live data
2. Writes collected data to workspace files (matching snapshot format)
3. Uses `offline_incident_analysis` tools on the collected data
4. Generates diagnosis using the same workflow as offline scenarios

**Note**: Templates without frontmatter will load all configured MCP servers (backward compatible).

---

### 3. Evaluate Agent Output

Evaluate agent outputs against ground truth using the `itbench_evaluations` judge (LLM-as-a-Judge).

```bash
# Batch evaluate agent output against ground truth
# Point to the extracted scenario directory (replace with your actual directory name)
# Make sure judge environment variables are set (see Environment Variables section)
JUDGE_BASE_URL="https://openrouter.ai/api/v1" \
JUDGE_API_KEY="$OPENROUTER_API_KEY" \
JUDGE_MODEL="google/gemini-2.5-pro" \
uv run itbench-eval \
  --ground-truth ./ITBench-Lite/snapshots/sre/v0.2-B96DF826-4BB2-4B62-97AB-6D84254C53D7 \
  --outputs ./outputs/agent_outputs \
  --result-file ./outputs/evaluation_results.json
```

Notes:
- `--ground-truth` should point to the directory containing scenario subdirectories (e.g., `Scenario-1`, `Scenario-2`, etc.), each with a `ground_truth.yaml` file
- Alternatively, `--ground-truth` can be a single consolidated JSON/YAML file
- The `--outputs` directory should contain subdirectories for each scenario (e.g., `2/1/agent_output.json`, `2/2/agent_output.json`)
- Results are written to `outputs/evaluation_results.json`
- Metrics are produced as floats in [0,1] (precision/recall/F1)

---

## Output Structure

The framework uses a consolidated `outputs/` directory structure:

```
outputs/
├── agent_outputs/              # All agent run workspaces
│   └── <incident_id>/          # e.g., 2/ for Scenario-2
│       └── <trial_number>/     # e.g., 1/, 2/, 3/
│           ├── agent_output.json       # Agent's incident diagnosis
│           ├── config.toml             # Codex configuration
│           ├── AGENTS.md               # System prompt
│           ├── agent_generated_code/   # Python scripts generated by agent
│           └── traces/
│               ├── traces.jsonl        # OTEL traces
│               └── stdout.log          # Console output
└── evaluation_results.json     # Judge scores and statistics
```

---

## Metrics

The judge evaluates agent outputs on these metrics:

| Metric | Description | Range |
|--------|-------------|-------|
| `root_cause_entity_*` | Root cause entity precision/recall/F1 | 0.0–1.0 |
| `root_cause_entity_k_*` | Root cause entity@k precision/recall/F1 | 0.0–1.0 |
| `root_cause_reasoning` | Reasoning correctness | 0.0–1.0 |
| `root_cause_reasoning_partial` | Partial credit for reasoning | 0.0–1.0 |
| `propagation_chain` | Failure propagation chain score | 0.0–1.0 |
| `fault_localization_component_identification` | Component-level localization (pass/fail) | 0 or 1 |
| `root_cause_proximity_*` | Proximity precision/recall/F1 | 0.0–1.0 |

---

## Project Structure

```
ITBench-SRE-Agent/
├── README.md                      # This file
├── model_leaderboard.toml         # Example configuration
├── litellm_config.yaml            # LiteLLM proxy config
├── pyproject.toml                 # Python project config
│
├── zero/                          # Agent runner (Codex wrapper)
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Workspace setup
│   ├── runner.py                  # Codex execution
│   └── zero-config/               # Bundled config
│       ├── README.md              # Zero documentation
│       ├── config.toml            # Codex config template
│       └── prompts/               # Prompt templates
│           └── react_shell_investigation.md  # Main SRE prompt
│
├── itbench_evaluations/           # LLM-as-a-Judge
│   ├── __main__.py                # `itbench-eval` CLI entrypoint
│   ├── agent.py                   # Evaluator
│   ├── loader.py                  # GT/output loaders
│   ├── aggregator.py              # Statistics
│   └── prompts/                   # Judge prompts
│
├── sre_tools/                     # MCP tools for SRE
│   ├── README.md                  # Full tool documentation
│   ├── utils.py                   # Shared utilities
│   └── offline_incident_analysis/ # Tool implementations
│       └── tools.py               # All SRE analysis tools
│
└── ITBench-Lite/                  # Benchmark data (downloaded from HF)
    └── snapshots/sre/...
```

---

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Format code
uv run black .
uv run isort .

# Run single agent test
uv run python -m zero --workspace /tmp/test --dry-run \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=/path/to/scenario" \
    -- exec -m "gpt-5.2"
```

---

## Troubleshooting

### Agent produces no output

1. Check `traces/stdout.log` for errors
2. Verify API key is set correctly
3. Check `wire_api` setting matches model provider
4. Try with `--verbose` flag

### Judge gives 0 scores

1. Verify `agent_output.json` has correct format
2. Check `judge_output.json` for error messages
3. Verify ground truth file exists

### Leaderboard skips scenarios

The leaderboard only skips scenarios where `agent_output.json` exists. Failed runs (missing output) will be re-run automatically.

---

## References

- [ITBench Benchmark](https://github.com/itbench-hub/ITBench-Lite)
- [Codex CLI](https://github.com/openai/codex)
- [Codex Configuration](https://github.com/openai/codex/blob/main/docs/config.md)
