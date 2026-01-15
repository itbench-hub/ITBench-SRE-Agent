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
# Clone with submodules (ITBench-Lite is a submodule)
git clone --recurse-submodules https://github.com/itbench-hub/ITBench-SRE-Agent.git
cd ITBench-SRE-Agent

# If you already cloned without --recurse-submodules, initialize the submodule:
# git submodule update --init --recursive

# Install dependencies
uv sync
# or: python -m venv .venv && source .venv/bin/activate && pip install -e .
```

### Environment Variables

```bash
# LiteLLM Proxy - API keys for model providers
export OPENROUTER_API_KEY="your-openrouter-key"    # For OpenRouter-proxied models
export OPENAI_API_KEY="your-openai-key"            # For direct OpenAI models

# Judge (itbench_evaluations) - uses OpenAI-compatible env vars
# The leaderboard sets these automatically from [judge] config, but set them
# yourself when running `itbench-eval` directly.
export JUDGE_BASE_URL="https://openrouter.ai/api/v1"
export JUDGE_API_KEY="$OPENROUTER_API_KEY"
export JUDGE_MODEL="google/gemini-2.5-pro"
```

---

## Running Components

### 1. Running LiteLLM Proxy (Required)

Before running agents, start the LiteLLM proxy in a separate terminal:

```bash
# Start LiteLLM proxy (runs on http://localhost:4000 by default)
litellm --config litellm_config.yaml

# Or with a custom port
litellm --config litellm_config.yaml --port 8080
```

Keep this terminal running while executing agent runs. The proxy provides a unified OpenAI-compatible endpoint for all configured models, using the API keys set in the environment variables above.


### 2. Run Agent Independently (Zero)

Zero is a thin wrapper around Codex CLI that handles workspace setup, prompt templating, and configuration.

```bash
# Basic run with prompt template
python -m zero --workspace /tmp/work \
    --read-only-dir ./ITBench-Lite/snapshots/sre/v0.1-.../Scenario-3 \
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

### 3. Evaluate Agent Output

Evaluate agent outputs against ground truth using the `itbench_evaluations` judge (LLM-as-a-Judge).

```bash
# Batch evaluate agent output against ground truth
itbench-eval \
  --ground-truth ./ITBench-Lite \
  --outputs ./agent_outputs \
  --result-file ./evaluation_results.json
```

Notes:
- `--ground-truth` can be either a directory like `./ITBench-Lite` (each subdir contains its own `ground_truth.yaml`) **or** a single consolidated JSON/YAML file.
- The `--outputs` directory should contain subdirectories for each scenario (e.g., `Scenario-1/1/agent_output.json`)
- Metrics are produced as floats in [0,1] (precision/recall/F1)

---

## Output Structure

Zero creates structured output directories for each agent run:

```
workspace/
├── agent_output.json           # Agent's incident diagnosis
├── config.toml                 # Codex configuration
├── AGENTS.md                   # System prompt
├── agent_generated_code/       # Python scripts generated by agent
└── traces/
    ├── traces.jsonl            # OTEL traces
    └── stdout.log              # Console output
```

Evaluation results:

```
evaluation_results.json         # Judge scores and statistics
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
└── ITBench-Lite/                  # Benchmark data (submodule)
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

- [ITBench Benchmark](https://github.com/itbench-hub/ITBench-Lite)
- [Codex CLI](https://github.com/openai/codex)
- [Codex Configuration](https://github.com/openai/codex/blob/main/docs/config.md)
