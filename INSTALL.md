# Installation Guide

## Prerequisites

- **Python 3.12 or 3.13** (required - avoid 3.14 due to compatibility issues)
- **uv** (recommended) or pip
- **Codex CLI** (for running agents)
- **[Podman](https://podman.io/docs/installation) or [Docker](https://docs.docker.com/get-docker/)** (required for ClickHouse MCP server)
- **API Keys** for LLM providers

---

## Quick Install

### Option 1: Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/itbench-hub/ITBench-SRE-Agent.git
cd ITBench-SRE-Agent

# Install with uv
uv sync

# Download benchmark scenarios from Hugging Face
# Start with a few scenarios to get started quickly (e.g., Scenario-2 and Scenario-5)
uv run huggingface-cli download \
  ibm-research/ITBench-Lite \
  --repo-type dataset \
  --include "snapshots/sre/v0.2-*/Scenario-2/**/*" \
  --include "snapshots/sre/v0.2-*/Scenario-5/**/*" \
  --local-dir ./ITBench-Lite

# Verify installation
uv run zero --help
uv run itbench-eval --help
```

### Option 2: Using pip

```bash
# Clone the repository
git clone https://github.com/itbench-hub/ITBench-SRE-Agent.git
cd ITBench-SRE-Agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package in editable mode
pip install -e .

# Download benchmark scenarios from Hugging Face
# Start with a few scenarios to get started quickly (e.g., Scenario-2 and Scenario-5)
huggingface-cli download \
  ibm-research/ITBench-Lite \
  --repo-type dataset \
  --include "snapshots/sre/v0.2-*/Scenario-2/**/*" \
  --include "snapshots/sre/v0.2-*/Scenario-5/**/*" \
  --local-dir ./ITBench-Lite

# Verify installation
zero --help
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

## Install Podman or Docker

Container runtime is required for ClickHouse MCP server:

```bash
# Podman (recommended - open source, daemonless)
brew install podman
podman machine init
podman machine start

# Or Docker (macOS via Homebrew)
brew install --cask docker

# Or download Docker Desktop: https://docs.docker.com/get-docker/

# Verify it's running
podman --version && podman ps
# or: docker --version && docker ps
```

> **Note:** If using Podman, create a `docker` alias: `alias docker=podman`

**Why containers?** We use container-based MCP servers ([Altinity MCP](https://github.com/Altinity/altinity-mcp) for ClickHouse) to avoid Python dependency conflicts with `litellm[proxy]`.

---

## Environment Variables

The project includes a comprehensive `.env.tmpl` template file with all configuration options.

```bash
# Copy the template to create your .env file
cp .env.tmpl .env

# Edit .env with your API keys and configuration
# At minimum, you need:
#   - OPENROUTER_API_KEY (primary model provider)

# Load environment variables before running Zero
source .env
```

The `.env.tmpl` template includes configuration for:
- **Model Provider API Keys**: OpenRouter (primary), OpenAI, WatsonX
- **Judge Configuration**: LLM-as-a-Judge evaluator settings
- **ClickHouse MCP Server**: Database connection settings
- **Kubernetes MCP Server**: Kubeconfig path

For detailed information about each variable, see the comments in [.env.tmpl](.env.tmpl).

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

### Common gotchas

- **`ModuleNotFoundError: No module named 'numpy'`**: you're running outside the managed environment.
  - If you installed with **uv**, run via uv: `uv run itbench-eval --help` (or `uv run python -m itbench_evaluations --help`).
  - If you installed with **pip**, make sure your venv is activated: `source .venv/bin/activate`.
- **Command name uses dashes**: the CLI is `itbench-eval` (not `itbench_evaluations`).

### 2. Check MCP tools module loads

```bash
# This should print "MCP tools module OK"
python -c "from sre_tools.offline_incident_analysis.tools import register_tools; print('MCP tools module OK')"

# List available SRE tools
python -c "
import re
from pathlib import Path
tools = re.findall(r'Tool\(\s*name=\"([^\"]+)\"', Path('sre_tools/offline_incident_analysis/tools.py').read_text())
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
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
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
| `itbench-eval` | LLM-as-a-Judge evaluation on saved outputs |

And these Python packages:

| Package | Description |
|---------|-------------|
| `zero` | Agent runner module |
| `sre_tools` | MCP tools for SRE analysis |
| `itbench_evaluations` | LLM-as-a-Judge evaluation |

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

The bundled config already includes the `offline_incident_analysis` MCP server. You do NOT need to modify `~/.codex/config.toml`.

If MCP tools still don't load, check:

```bash
# Ensure the MCP server can start
python -m sre_tools.offline_incident_analysis

# Check workspace config was created
ls -la /tmp/your-workspace/config.toml

# Look for MCP errors in Codex output
uv run zero --workspace /tmp/debug --verbose -- -m "openai/gpt-4o-mini"
```

### ITBench-Lite directory is empty or missing scenarios

The benchmark data needs to be downloaded from Hugging Face:

```bash
# Download specific scenarios (recommended - faster and smaller)
uv run huggingface-cli download \
  ibm-research/ITBench-Lite \
  --repo-type dataset \
  --include "snapshots/sre/v0.2-*/Scenario-2/**/*" \
  --include "snapshots/sre/v0.2-*/Scenario-5/**/*" \
  --local-dir ./ITBench-Lite

# Or download all scenarios if needed
# uv run huggingface-cli download \
#   ibm-research/ITBench-Lite \
#   --repo-type dataset \
#   --include "snapshots/sre/v0.2-*/Scenario-*/**/*" \
#   --local-dir ./ITBench-Lite

# Verify
ls ITBench-Lite/snapshots/sre/
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
- See [sre_tools/README.md](sre_tools/README.md) for MCP tool documentation
