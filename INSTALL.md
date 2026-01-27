# Installation Guide

## Prerequisites

- **Python 3.12+**  (required - avoid 3.14 due to compatibility issues)
- **[uv](https://github.com/astral-sh/uv)** (package manager)
- **[Node.js and npm](https://nodejs.org/)** (required to install Codex CLI)
- **Codex CLI** (for running agents)
- **[Podman](https://podman.io/docs/installation) or [Docker](https://docs.docker.com/get-docker/)** (required for ClickHouse MCP server)
- **API Keys** for LLM providers

---

## Quick Install

```bash
# Clone the repository with submodules
git clone --recurse-submodules https://github.com/itbench-hub/ITBench-SRE-Agent.git
cd ITBench-SRE-Agent

# If you already cloned without --recurse-submodules, initialize submodules:
# git submodule update --init --recursive

# Install with uv
uv sync

# Download benchmark scenarios from Hugging Face
# Start with a few scenarios to get started quickly (e.g., Scenario-2 and Scenario-5)
uv run hf download \
  ibm-research/ITBench-Lite \
  --repo-type dataset \
  --include "snapshots/sre/v0.2-*/Scenario-2/*" \
  --include "snapshots/sre/v0.2-*/Scenario-5/*" \
  --local-dir ./ITBench-Lite

# Verify installation
uv run python -m zero --help
uv run python -m itbench_evaluations --help
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

Container runtime is required for MCP servers (ClickHouse, Instana):

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

**Why containers?** We use container-based MCP servers to avoid Python dependency conflicts:
- **ClickHouse**: Official [mcp-clickhouse](https://github.com/ClickHouse/mcp-clickhouse) - avoids `uvicorn` version conflicts
- **Instana**: Official [mcp-instana](https://github.com/instana/mcp-instana) - avoids `rich` package conflicts (litellm needs `rich==13.7.1`, mcp-instana needs `rich>=13.9.4`)

### Pull/Build MCP Server Images

**ClickHouse MCP (pre-built image available):**
```bash
# Pull ClickHouse MCP server (for live environment metrics/logs)
podman pull docker.io/mcp/clickhouse:latest
# (or: docker pull docker.io/mcp/clickhouse:latest)
```

**Instana MCP (requires local build - no pre-built image):**
```bash
# Initialize the submodule (included in this repository)
git submodule update --init --recursive

# Build Instana MCP server (for Instana APM integration - optional)
cd sre_tools/instana_mcp/mcp-instana
podman build -t mcp-instana:latest .
# (or: docker build -t mcp-instana:latest .)
cd ../../..
```

**Verify images:**
```bash
podman images | grep -E "mcp/clickhouse|mcp-instana"
# (or: docker images | grep -E "mcp/clickhouse|mcp-instana")
```

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
- **Instana MCP Server**: Instana APM connection settings (optional)

For detailed information about each variable, see the comments in [.env.tmpl](.env.tmpl).

---

## Verify Installation

### 1. Check CLI tools are available

```bash
# Zero agent runner
uv run python -m zero --help

# Leaderboard runner
uv run python -m itbench_leaderboard --help

# Judge runner
uv run python -m itbench_evaluations --help
```

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
uv run python -m zero --workspace /tmp/test-interactive \
    -- -m "openai/gpt-4o-mini"
```

**Exec mode** (non-interactive - for automation):

```bash
# Run agent with prompt template (requires a valid snapshot directory)
uv run python -m zero --workspace /tmp/test-exec \
    --prompt-file ./zero/zero-config/prompts/react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=/path/to/ITBench-Lite/snapshots/sre/v0.2-.../Scenario-1" \
    -- exec --full-auto -m "openai/gpt-4o-mini" \
    "Start the investigation"
```

**Simple exec test** (no prompt file):

```bash
# Quick test without prompt template
uv run python -m zero --workspace /tmp/test-simple \
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

Make sure the package is installed:

```bash
uv run zero --help
# or: which zero (if using uv shell)
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
uv run hf download \
  ibm-research/ITBench-Lite \
  --repo-type dataset \
  --include "snapshots/sre/v0.2-*/Scenario-2/*" \
  --include "snapshots/sre/v0.2-*/Scenario-5/*" \
  --local-dir ./ITBench-Lite

# Or download all scenarios if needed
# uv run hf download \
#   ibm-research/ITBench-Lite \
#   --repo-type dataset \
#   --include "snapshots/sre/v0.2-*/Scenario-*" \
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
