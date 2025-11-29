# SRE Support Agent

A diagnostic SRE (Site Reliability Engineering) agent built with [LangGraph](https://github.com/langchain-ai/langgraph) and [litellm](https://github.com/BerriAI/litellm). This agent is designed to help diagnose system issues by providing controlled access to file operations, search capabilities, and system commands.

## Features

*   **Diagnostic Tools**:
    *   **File Operations**: Read, list directories (edit/delete/create can be disabled).
    *   **Search**: Grep, file name search, and basic codebase search.
    *   **System**: Execute terminal commands (sandboxed by configuration).
*   **Fine-Grained Control**: Enable or disable individual tools via configuration to ensure safety.
*   **Model Agnostic**: Supports various LLM backends via litellm (OpenAI, Anthropic, Google, Azure, AWS Bedrock, etc.).
*   **Blacklist Support**: Prevent access to sensitive files using glob patterns.
*   **Configuration**: TOML-based configuration for easy setup.

## Prerequisites

*   Python 3.12+
*   [uv](https://github.com/astral-sh/uv) (Recommended for dependency management)

## Installation

1.  **Clone the repository with submodules** (if you haven't already):
    ```bash
    git clone --recurse-submodules <repository-url>
    cd sre_support_agent
    ```

    If you've already cloned the repository without submodules, initialize them:
    ```bash
    git submodule update --init --recursive
    ```

2.  **Create a virtual environment and install dependencies**:

    Using `uv` (Recommended):
    ```bash
    uv sync
    ```

    Using standard `pip`:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

## Configuration

The agent is configured via an `agent.toml` file. A template is provided as `agent.toml.example`.

### Quick Start

1.  **Copy the example configuration**:
    ```bash
    cp agent.toml.example agent.toml
    ```

2.  **Edit `agent.toml`** and configure:
    *   **Model**: Set `model_name` to your preferred model (see examples in the file)
    *   **API Key**: Set your API key in `[llm_config]`
    *   **Base URL**: Set the API endpoint (OpenRouter, litellm proxy, etc.)
    *   **Base Directory**: Set `base_dir` in `[file_tools]` to the scenario directory

### Configuration Options

```toml
# agents/sre/agent.toml

# --- Model Configuration ---
# For OpenRouter: "openrouter/provider/model-name"
# For litellm proxy: "litellm_proxy/provider/model-name"
model_name = "openrouter/anthropic/claude-opus-4.5"

# Agent execution limit (each tool call = 2 steps)
recursion_limit = 100

# Max characters for tool output when summarization is disabled
max_tool_output_length = 10000

[llm_config]
api_key = "your-api-key"
base_url = "https://openrouter.ai/api/v1"

# --- Tool Configuration ---

[file_tools]
enabled = true
base_dir = "./snapshots/scenario"  # Restrict operations to this directory
enable_read_file = true
enable_list_directory = true
# Dangerous operations disabled by default
enable_edit_file = false
enable_create_file = false
enable_delete_file = false

[search_tools]
enabled = true
max_results = 20
enable_grep = true
enable_file_search = true
enable_codebase_search = true

[system_tools]
enabled = true
enable_run_terminal_cmd = true

[blacklist]
# Files matching these patterns cannot be read, grepped, or listed
patterns = [
    "ground_truth*.yaml",
    "*.secret",
    "*.key",
    ".env*",
]
```

### Environment Variables

You can also set API keys via environment variables:
```bash
export OPENAI_API_KEY="your-api-key"
# or for OpenRouter
export OPENROUTER_API_KEY="your-key"
```

## Usage

Run the agent as a Python module:

```bash
# From the agents/sre directory
python -m sre_support_agent "Diagnose the incident"

# With a specific scenario directory
python -m sre_support_agent --dir ./snapshots/Scenario-3 "Investigate alerts"

# With a custom config file
python -m sre_support_agent --config custom.toml "Diagnose the incident"
```

### Example Queries
*   "Diagnose the incident"
*   "Investigate the alerts and find the contributing factors"
*   "Analyze the kubernetes events and traces to find the issue"

## Validation & Leaderboard

The repository includes [ITBench-Snapshots](https://github.com/itbench-hub/ITBench-Snapshots) as a submodule, which contains benchmark scenarios for validating SRE agent performance.

### Running a Single Scenario

To validate your agent against a specific benchmark scenario:

```bash
# Run the agent against a specific scenario
python -m sre_support_agent --dir ./ITBench-Snapshots/snapshots/sre/v0.1-ca9707b2-8b70-468b-a8f9-9658438f80b1/ca9707b2-8b70-468b-a8f9-9658438f80b1/Scenario-3 "Diagnose the incident"
```

### Running the Full Benchmark

Use `create_leaderboard.py` to evaluate the agent across all scenarios and generate leaderboard results:

```bash
# Basic usage (uses config from agent.toml)
python create_leaderboard.py

# Specify a different model for the agent
python create_leaderboard.py --model_name openrouter/anthropic/claude-sonnet-4

# Full configuration with custom API endpoints
python create_leaderboard.py \
    --model_name openrouter/anthropic/claude-sonnet-4 \
    --base_url https://openrouter.ai/api/v1 \
    --api_key your-agent-api-key \
    --judge_model google/gemini-2.5-pro \
    --judge_base_url https://openrouter.ai/api/v1 \
    --judge_api_key your-judge-api-key

# Run fewer iterations (default is 5 runs per scenario)
python create_leaderboard.py --runs 3

# Run specific scenarios only
python create_leaderboard.py --scenarios Scenario-3 Scenario-16
```

#### CLI Options

| Option | Description |
|--------|-------------|
| `--model_name` | Model name for the SRE agent (overrides config) |
| `--base_url` | Base URL for the SRE agent API |
| `--api_key` | API key for the SRE agent |
| `--judge_model` | Model for LLM-as-judge evaluation (default: `google/gemini-2.5-pro`) |
| `--judge_base_url` | Base URL for judge model API (default: OpenRouter) |
| `--judge_api_key` | API key for judge model (or set `OPENROUTER_API_KEY` env var) |
| `--runs` | Number of runs per scenario (default: 5) |
| `--scenarios` | Specific scenarios to evaluate |
| `--config` | Path to base config file |
| `--output` | Custom output file path |

### Viewing the Leaderboard

Results are saved to `website/results/result_<model_name>.json`. To view the leaderboard:

```bash
# Serve the static website locally
cd website
python -m http.server 8000
# Open http://localhost:8000 in your browser
```

The leaderboard displays:
- **Rankings**: Models sorted by average score (descending)
- **Per-scenario breakdown**: Click any model to see detailed per-scenario results
- **Variability metrics**: Min/max/avg scores across multiple runs

## Development

This project uses `black` and `isort` for code formatting.

**Install dev dependencies:**
```bash
uv sync --extra dev
```

**Format code:**
```bash
uv run black sre_support_agent/
uv run isort sre_support_agent/
```

## Project Structure

```
sre_support_agent/
├── agent.toml.example      # Configuration template (copy to agent.toml)
├── create_leaderboard.py   # Benchmark evaluation script
├── pyproject.toml          # Project metadata and dependencies
├── requirements.txt        # Dependencies for pip install
├── README.md
├── ITBench-Snapshots/      # Benchmark scenarios (git submodule)
├── website/                # Static leaderboard website
│   ├── index.html          # Leaderboard UI
│   └── results/            # Generated result JSON files
└── sre_support_agent/      # Main package
    ├── __init__.py
    ├── __main__.py         # Entry point for `python -m sre_support_agent`
    ├── config.py           # Configuration models
    ├── graph.py            # LangGraph workflow definition
    ├── langchain_tools.py  # Tool wrappers with schema generation
    ├── main.py             # Main execution logic
    ├── prompts.py          # System prompts
    └── tools/              # Tool implementations
        ├── __init__.py
        ├── file_tools.py
        ├── search_tools.py
        ├── system_tools.py
        └── task_tools.py
```

## Supported Models

The agent uses litellm for model compatibility. Some tested models:

| Provider | Model | Notes |
|----------|-------|-------|
| OpenRouter | `openrouter/anthropic/claude-opus-4.5` | Excellent tool calling |
| OpenRouter | `openrouter/openai/gpt-5.1` | Good performance |
| OpenRouter | `openrouter/google/gemini-2.5-pro` | Good performance |
| OpenRouter | `openrouter/qwen/qwen3-max` | Good tool calling |
| Azure | `litellm_proxy/Azure/gpt-5.1-*` | Via litellm proxy |
| AWS | `litellm_proxy/aws/claude-opus-4-5` | Via litellm proxy |
| GCP | `litellm_proxy/GCP/gemini-2.5-pro` | Via litellm proxy |

**Note**: Gemini 3 models currently have issues with thought signatures in multi-turn tool calling.
