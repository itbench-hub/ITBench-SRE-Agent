# ITBench SRE Agent

A modular framework for evaluating LLM agents on Site Reliability Engineering (SRE) incident diagnosis tasks using the [ITBench](https://github.com/itbench-hub/ITBench-Snapshots) benchmark.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ITBench SRE Framework                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────────┐  │
│  │    Zero      │───▶│  ITBench         │───▶│   ITBench Evaluations    │  │
│  │ Agent Runner │    │  Leaderboard     │    │   (LLM-as-a-Judge)       │  │
│  └──────────────┘    └──────────────────┘    └──────────────────────────┘  │
│        │                     │                          │                   │
│        ▼                     ▼                          ▼                   │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────────┐  │
│  │   Codex CLI  │    │ model_leaderboard│    │   agent_output.json      │  │
│  │  (OpenAI)    │    │     .toml        │    │   judge_output.json      │  │
│  └──────────────┘    └──────────────────┘    └──────────────────────────┘  │
│                                                                             │
│                              ┌─────────────────┐                            │
│                              │    Website      │                            │
│                              │  (Leaderboard)  │                            │
│                              └─────────────────┘                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Components

| Module | Description | Documentation |
|--------|-------------|---------------|
| **[Zero](./zero/)** | Thin wrapper around [Codex CLI](https://github.com/openai/codex) for running SRE agents | [zero/zero-config/README.md](./zero/zero-config/README.md) |
| **[ITBench Leaderboard](./itbench_leaderboard/)** | Orchestrates agent runs across scenarios, collects results | [itbench_leaderboard/README.md](./itbench_leaderboard/README.md) |
| **[ITBench Evaluations](./itbench_evaluations/)** | LLM-as-a-Judge evaluator for agent outputs (direct OpenAI/OpenAI-compatible SDK) | `itbench_evaluations/` |
| **[Website](./website/)** | Static leaderboard visualization | [website/README.md](./website/README.md) |
| **[SRE Tools](./sre_tools/)** | MCP server with SRE diagnostic tools | [sre_tools/README.md](./sre_tools/README.md) |

### SRE Tools Overview

The SRE Tools module provides specialized MCP (Model Context Protocol) tools for incident investigation. These tools are automatically available to agents via the Zero runner.

| Tool | Description | Use Case |
|------|-------------|----------|
| **`alert_summary`** ⭐ | High-level overview of all alerts | **Start here** - Get alert types, entities, duration, frequency |
| **`alert_analysis`** | Detailed alert analysis with filters/grouping | Filter by severity, group by alertname, track duration |
| **`event_analysis`** | Analyze K8s events | Find warnings, unhealthy pods, scheduling issues |
| **`metric_analysis`** | Batch metric queries with derived metrics | CPU throttling %, memory utilization across pods |
| **`get_metric_anomalies`** | Detect metric anomalies | Find CPU spikes, memory leaks, error rate increases |
| **`get_trace_error_tree`** | Analyze distributed traces | Find where transactions fail in call chain |
| **`build_topology`** | Build operational topology graph | Map service dependencies, K8s object relationships |
| **`topology_analysis`** | Analyze entity dependencies | Find upstream/downstream services, call chains |
| **`k8s_spec_change_analysis`** | Track K8s spec changes | Identify config drift, correlate incidents with changes |
| **`get_context_contract`** ⭐ | Aggregate full entity context | **All-in-one**: events, alerts, traces, metrics, dependencies |

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

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- [Codex CLI](https://github.com/openai/codex) installed (`npm install -g @openai/codex`)
- API keys for your model provider (OpenRouter, Azure, etc.)

### Installation

```bash
# Clone with submodules (ITBench-Snapshots is a submodule)
git clone --recurse-submodules <repository-url>
cd sre_support_agent

# Install dependencies
uv sync
# or: python -m venv .venv && source .venv/bin/activate && pip install -e .
```

### Environment Variables

```bash
# Agent model provider keys (used by Zero runs)
export OR_API_KEY="your-openrouter-key"              # OpenRouter (agents)
export ETE_API_KEY="your-ete-key"                    # ETE LiteLLM Proxy (agents)
export AZURE_OPENAI_API_KEY="your-azure-key"         # Azure OpenAI (agents)

# Judge (itbench_evaluations) uses OpenAI-compatible env vars.
# The leaderboard sets these automatically from [judge] config, but set them
# yourself when running `itbench-eval` directly.
export JUDGE_BASE_URL="https://openrouter.ai/api/v1"
export JUDGE_API_KEY="$OR_API_KEY"
export JUDGE_MODEL="google/gemini-2.5-pro"
```

---

## Running Components

### 1. Running LiteLLM Proxy (Required)

Before running agents, start the LiteLLM proxy in a separate terminal:
```bash
# Required environment variables for LiteLLM
export OPENROUTER_API_KEY="your-openrouter-key"    # For OpenRouter-proxied models
export OPENAI_API_KEY="your-openai-key"            # For direct OpenAI models

# Start LiteLLM proxy (runs on http://localhost:4000 by default)
litellm --config litellm_config.yaml

# Or with a custom port
litellm --config litellm_config.yaml --port 8080
```

Keep this terminal running while executing agent runs. The proxy provides a unified OpenAI-compatible endpoint for all configured models.


### 2. Run Agent Independently (Zero)

Zero is a thin wrapper around Codex CLI that handles workspace setup, prompt templating, and configuration.

```bash
# Basic run with prompt template
python -m zero --workspace /tmp/work \
    --read-only-dir ./ITBench-Snapshots/snapshots/sre/v0.1-.../Scenario-3 \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=/path/to/Scenario-3" \
    -- exec --full-auto -m "Azure/gpt-5.1-2025-11-13"

# With additional user query
python -m zero --workspace /tmp/work \
    --read-only-dir ./Scenario-3 \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=/path/to/Scenario-3" \
    -- exec --full-auto -m "google/gemini-2.5-pro" \
    "Focus on the payment service alerts"

# Interactive mode (TUI)
python -m zero --workspace /tmp/work \
    --read-only-dir ./Scenario-3 \
    -- -m "openai/gpt-5.1"
```

📖 **Full documentation**: [zero/zero-config/README.md](./zero/zero-config/README.md)

### 3. Run Judge Independently

Evaluate agent outputs against ground truth using the `itbench_evaluations` judge (recommended via the `itbench-eval` CLI).

```bash
# Batch evaluate all trials under an outputs directory (leaderboard_results layout)
itbench-eval \
  --ground-truth ./ITBench-Snapshots \
  --outputs ./leaderboard_results/react\ with\ code_google_gemini-2.5-pro_d4cd266 \
  --result-file ./evaluation_results.json
```

Notes:
- `--ground-truth` can be either a directory like `./ITBench-Snapshots` (each subdir contains its own `ground_truth.yaml`) **or** a single consolidated JSON/YAML file.
- Metrics are produced as floats in \([0,1]\) (precision/recall/F1); the leaderboard prints them as percentages.

### 4. Run Leaderboard (Full Benchmark)

The leaderboard orchestrates running multiple agents across all scenarios with multiple runs for statistical significance.

```bash
# Configure agents in model_leaderboard.toml, then:
python -m itbench_leaderboard --config model_leaderboard.toml

# With options
python -m itbench_leaderboard --config model_leaderboard.toml \
    --runs 3 \                    # 3 runs per scenario
    --agents gpt-5.1-azure \      # Only run specific agent
    --scenarios Scenario-3 \      # Only run specific scenario
    --verbose

# Re-judge existing outputs (without re-running agents)
python -m itbench_leaderboard --config model_leaderboard.toml --rejudge

# Smoke test: 2 incidents, 1 run
python -m itbench_leaderboard --config model_leaderboard.toml --scenarios 1 2 --runs 1
```

📖 **Full documentation**: [itbench_leaderboard/README.md](./itbench_leaderboard/README.md)

---

## Configuration

### model_leaderboard.toml

```toml
# Scenarios and output
scenarios_dir = "./ITBench-Snapshots/snapshots/sre/v0.1-..."
leaderboard_dir = "./leaderboard_results"
runs_per_scenario = 3
concurrent = true
max_workers = 3

# Judge configuration
[judge]
model = "google/gemini-2.5-pro"
provider = "openrouter"
base_url = "https://openrouter.ai/api/v1"

# Agent configurations
[[agents]]
name = "gpt-5.1-azure"
model = "Azure/gpt-5.1-2025-11-13"
provider = "ete"
prompt_file = "./zero/zero-config/prompts/react_shell_investigation.md"
wire_api = "responses"  # "chat" for non-OpenAI models

[[agents]]
name = "gemini-2.5-pro"
model = "google/gemini-2.5-pro"
provider = "openrouter"
prompt_file = "./zero/zero-config/prompts/react_shell_investigation.md"
wire_api = "chat"  # Required for Gemini!
```

### wire_api Setting (Critical!)

| Model Provider | wire_api |
|----------------|----------|
| OpenAI (gpt-*, o*-mini) | `responses` |
| Azure OpenAI | `responses` |
| Anthropic (claude-*) | `chat` ⚠️ |
| Google (gemini-*) | `chat` ⚠️ |
| Other models | `chat` ⚠️ |

**Using `wire_api = "responses"` with non-OpenAI models will cause function calls to fail!**

---

## Output Structure

```
leaderboard_results/
├── gpt-5.1-azure/
│   ├── Scenario-1/
│   │   ├── 1/                          # Run 1
│   │   │   ├── agent_output.json       # Agent diagnosis
│   │   │   ├── judge_output.json       # Judge evaluation
│   │   │   ├── AGENTS.md               # Prompt given to agent
│   │   │   ├── config.toml             # Codex config
│   │   │   └── traces/
│   │   │       └── traces.jsonl        # OTEL traces
│   │   ├── 2/                          # Run 2
│   │   └── 3/                          # Run 3
│   └── Scenario-3/
│       └── ...
├── gemini-2.5-pro/
│   └── ...
└── results/
    ├── gpt-5.1-azure.json              # Per-agent results
    ├── gemini-2.5-pro.json
    └── leaderboard.json                # Combined leaderboard
```

---

## Viewing Results

### Leaderboard Website

```bash
cd website
python -m http.server 8000
# Open http://localhost:8000
```

### JSON Results

```bash
# View leaderboard rankings
cat leaderboard_results/results/leaderboard.json | jq '.rankings'

# View per-scenario breakdown
cat leaderboard_results/results/gpt-5.1-azure.json | jq '.scenarios'
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
sre_support_agent/
├── README.md                      # This file
├── model_leaderboard.toml         # Leaderboard configuration
├── pyproject.toml                 # Python project config
├── requirements.txt
│
├── zero/                          # Agent runner (Codex wrapper)
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Workspace setup
│   ├── runner.py                  # Codex execution
│   └── zero-config/               # Bundled config
│       ├── README.md              # Zero documentation
│       ├── config.toml            # Codex config template
│       ├── prompts/               # Prompt templates
│       │   └── react_shell_investigation.md  # Main SRE prompt
│       └── policy/                # Execution policies
│
├── itbench_leaderboard/           # Leaderboard orchestrator
│   ├── README.md
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # TOML config loader
│   ├── runner.py                  # Agent subprocess runner
│   └── results.py                 # Results aggregation
│
├── itbench_evaluations/           # LLM-as-a-Judge (direct OpenAI SDK)
│   ├── __main__.py                # `itbench-eval` CLI entrypoint
│   ├── agent.py                   # LAAJ evaluator
│   ├── loader.py                  # GT/output loaders
│   └── prompts/                   # Judge prompts
│
├── sre_tools/                     # MCP tools for SRE
│   ├── README.md                  # Full tool documentation
│   ├── manifest.toml              # Tool registry
│   ├── utils.py                   # Shared utilities
│   └── offline_incident_analysis/             # Tool implementations
│       └── tools.py               # All SRE analysis tools
│
├── website/                       # Static leaderboard UI
│   ├── README.md
│   ├── index.html
│   └── results/                   # Generated JSON results
│
├── ITBench-Snapshots/             # Benchmark data (submodule)
│   └── snapshots/sre/...
│
└── workspace/                     # Shared data
    └── shared/
        └── application_architecture.json
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
python -m zero --workspace /tmp/test --dry-run \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=/path/to/scenario" \
    -- exec -m "openai/gpt-5.1"
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

- [ITBench Benchmark](https://github.com/itbench-hub/ITBench-Snapshots)
- [Codex CLI](https://github.com/openai/codex)
- [Codex Configuration](https://github.com/openai/codex/blob/main/docs/config.md)
