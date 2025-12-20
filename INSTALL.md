# Installation Guide

## Prerequisites

- **Python 3.12+** (required)
- **uv** (recommended) or pip
- **Codex CLI** (for running agents)
- **API Keys** for LLM providers

---

## Quick Install

### Option 1: Using uv (Recommended)

```bash
# Clone the repository with submodules
git clone --recurse-submodules https://github.com/YOUR_ORG/sre_support_agent.git
cd sre_support_agent

# If you already cloned without --recurse-submodules:
git submodule update --init --recursive

# Install with uv
uv sync

# Verify installation
uv run zero --help
uv run itbench-leaderboard --help
uv run itbench-eval --help
```

### Option 2: Using pip

```bash
# Clone the repository with submodules
git clone --recurse-submodules https://github.com/YOUR_ORG/sre_support_agent.git
cd sre_support_agent

# If you already cloned without --recurse-submodules:
git submodule update --init --recursive

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package in editable mode
pip install -e .

# Verify installation
zero --help
itbench-leaderboard --help
itbench-eval --help
```

---

## Install Codex CLI

The `zero` agent runner requires the OpenAI Codex CLI:

```bash
# Install Codex CLI (requires Node.js 22+)
npm install -g @openai/codex
# tested with version 0.69 and 0.71
```

Or follow the official instructions: https://github.com/openai/codex

---

## Environment Variables

Create a `.env` file or export these environment variables:

```bash
# Required: at least one agent provider API key
export OPENAI_API_KEY="sk-..."                 # For OpenAI models (agents)
export OR_API_KEY="sk-or-..."                  # For OpenRouter models (agents)
export AZURE_OPENAI_API_KEY="..."              # For Azure OpenAI (agents)

# Optional: For specific providers
export ETE_API_KEY="..."                       # For ETE LiteLLM Proxy (agents)
export ANTHROPIC_API_KEY="..."                 # For Anthropic Claude
export GOOGLE_API_KEY="..."                    # For Google Gemini

# Judge (itbench_evaluations) uses OpenAI-compatible env vars.
# The leaderboard sets these automatically from `model_leaderboard.toml` [judge],
# but set them yourself when running `itbench-eval` directly.
export JUDGE_BASE_URL="https://openrouter.ai/api/v1"
export JUDGE_API_KEY="$OR_API_KEY"
export JUDGE_MODEL="google/gemini-2.5-pro"
```

---

## Verify Installation

### 1. Check CLI tools are available

```bash
# Zero agent runner
zero --help

# Leaderboard runner
itbench-leaderboard --help

# Judge runner
itbench-eval --help
```

### 2. Check MCP tools module loads

```bash
# This should print "MCP tools module OK"
python -c "from sre_tools.cli.sre_utils.tools import register_tools; print('MCP tools module OK')"

# List available SRE tools
python -c "
import re
from pathlib import Path
tools = re.findall(r'Tool\(\s*name=\"([^\"]+)\"', Path('sre_tools/cli/sre_utils/tools.py').read_text())
print('Available SRE MCP tools:')
for t in tools: print(f'  - {t}')
"
```

Expected output:
```
Available SRE MCP tools:
  - build_topology
  - topology_analysis
  - metric_analysis
  - get_metric_anomalies
  - event_analysis
  - get_trace_error_tree
  - alert_analysis
  - alert_summary
  - k8s_spec_change_analysis
  - get_context_contract
```

### 3. Run a quick test (optional)

**Interactive mode** (TUI - for exploration):

```bash
# Opens Codex TUI with MCP tools available
uv run zero --workspace /tmp/test-interactive \
    -- -m "openai/gpt-4o-mini"
```

**Exec mode** (non-interactive - for automation):

```bash
# Run agent with prompt template (requires a valid snapshot directory)
uv run zero --workspace /tmp/test-exec \
    --prompt-file ./zero/zero-config/prompts/tap.md \
    --variable "SNAPSHOT_DIRS=/path/to/ITBench-Snapshots/snapshots/sre/v0.1-.../Scenario-1" \
    -- exec --full-auto -m "openai/gpt-4o-mini" \
    "Start the investigation"
```

**Simple exec test** (no prompt file):

```bash
# Quick test without prompt template
uv run zero --workspace /tmp/test-simple \
    -- exec -m "openai/gpt-4o-mini" "What tools do you have available?"
```

---

## Project Structure

After installation, you'll have these CLI commands:

| Command | Description |
|---------|-------------|
| `zero` | Agent runner (wraps Codex CLI) |
| `itbench-leaderboard` | Run benchmarks and evaluate agents |
| `itbench-eval` | Run judge directly on saved outputs |

And these Python packages:

| Package | Description |
|---------|-------------|
| `zero` | Agent runner module |
| `sre_tools` | MCP tools for SRE analysis |
| `itbench_evaluations` | LLM-as-a-Judge evaluation (direct OpenAI SDK) |
| `itbench_leaderboard` | Benchmark orchestration |

---

## Troubleshooting

### "Command not found: zero"

Make sure the package is installed and your virtual environment is activated:

```bash
source .venv/bin/activate  # or: uv shell
which zero
```

### "ModuleNotFoundError: No module named 'tomllib'"

You're on Python < 3.11. Install tomli:

```bash
pip install tomli
```

### Codex CLI not working

1. Ensure Node.js 22+ is installed
2. Check Codex is in PATH: `which codex`
3. Verify API key: `echo $OPENAI_API_KEY`

### MCP tools not loading in Codex

**Zero handles MCP configuration automatically.** When you run `zero`, it:

1. Copies its bundled `config.toml` (from `zero/zero-config/`) to the workspace
2. Sets `CODEX_HOME` to the workspace directory
3. Codex reads the config from the workspace, not from `~/.codex/`

The bundled config already includes the `sre_utils` MCP server. You do NOT need to modify `~/.codex/config.toml`.

If MCP tools still don't load, check:

```bash
# Ensure the MCP server can start
python -m sre_tools.cli.sre_utils

# Check workspace config was created
ls -la /tmp/your-workspace/config.toml

# Look for MCP errors in Codex output
uv run zero --workspace /tmp/debug --verbose -- -m "openai/gpt-4o-mini"
```

### ITBench-Snapshots directory is empty

The benchmark data is in a git submodule. Initialize it:

```bash
git submodule update --init --recursive

# Verify
ls ITBench-Snapshots/snapshots/sre/
```

### Agent not producing output file

If `agent_output.json` is not created:

1. Zero will automatically retry with `resume --last` (up to 5 times by default)
2. Check `--max-retries` flag to adjust retry count
3. Ensure your prompt instructs the agent to write to `$WORKSPACE_DIR/agent_output.json`

---

## Next Steps

- See [README.md](README.md) for usage examples
- See [zero/zero-config/README.md](zero/zero-config/README.md) for agent configuration
- See [itbench_leaderboard/README.md](itbench_leaderboard/README.md) for running benchmarks
- See [sre_tools/README.md](sre_tools/README.md) for MCP tool documentation
