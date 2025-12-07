# Zero Configuration

This directory contains configuration files for the `sre_support_engineer` profile.

## Quick Start

```bash
# Use zero-config directory directly as CODEX_HOME
export CODEX_HOME=/path/to/zero-config

# Run with the profile
codex --profile sre_support_engineer "analyze the incident"

# Or one-liner
CODEX_HOME=./zero-config codex exec "analyze the incident"
```

## Summary

| Method | Command |
|--------|---------|
| **CODEX_HOME** | `CODEX_HOME=./zero-config codex exec "task"` |
| **CLI flags** | `codex exec -c 'model="o3"' -c 'model_reasoning_effort="high"' "task"` |
| **Copy to ~/.codex** | Traditional installation (see Option B below) |

The `zero-config/` directory is fully portable - just set `CODEX_HOME` to point to it and everything (config, prompts, policies) will be loaded from there.

## Using Zero CLI

Zero provides a higher-level CLI wrapper around Codex with session management:

```bash
# Basic usage
python -m zero --session-dir /tmp/session --read-only-dir /path/to/Scenario-1

# Multiple read-only directories
python -m zero --session-dir /tmp/session \
  --read-only-dir /path/to/scenario \
  --read-only-dir /path/to/shared-data

# With tracing enabled
python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \
  --collect-traces
```

## Installation

### Option A: Use as standalone CODEX_HOME (Recommended)

Use this directory directly without copying:

```bash
# Set CODEX_HOME to point to this directory
export CODEX_HOME=/path/to/zero-config

# Run codex - it will use all config from this directory
codex --profile sre_support_engineer "analyze the incident"

# Or with codex exec
codex exec --profile sre_support_engineer "analyze the incident"
```

### Option B: Copy to ~/.codex

Copy the files to your default Codex home directory:

```bash
# Create directories
mkdir -p ~/.codex/policy ~/.codex/prompts /tmp/zero-session

# Copy configuration files
cp config.toml ~/.codex/config.toml
cp policy/sre_support_engineer.codexpolicy ~/.codex/policy/
cp prompts/sre_support_engineer.md ~/.codex/prompts/
```

### Option C: Pass config via command line

```bash
codex exec \
  -c 'model="o3"' \
  -c 'model_reasoning_effort="high"' \
  -c 'experimental_instructions_file="/path/to/sre_support_engineer.md"' \
  -c 'approval_policy="never"' \
  "analyze the incident"
```

## What's Included

### Profile: `sre_support_engineer`

A profile designed for investigating Kubernetes incidents from captured snapshots.

**Configuration:**

| Setting | Value | Description |
|---------|-------|-------------|
| `model` | `o3` | High-capability reasoning model |
| `model_provider` | `openai` | Default OpenAI API |
| `model_reasoning_effort` | `high` | Maximum reasoning for complex RCA |
| `model_reasoning_summary` | `detailed` | Full reasoning explanations |
| `sandbox_mode` | `workspace-write` | Allow writing output files |
| `approval_policy` | `never` | No prompts; execution policy controls access |

**Features:**
- Custom prompt focused on incident root cause analysis
- Auto-allows kubectl read commands (get, describe, logs, top, etc.)
- Forbids destructive operations (delete, apply, rm, mv, etc.)
- Outputs diagnosis to `output.json`
- Session-based directory structure for organized output

### Files

| File | Purpose |
|------|---------|
| `agent.toml` | Main config with the sre_support_engineer profile |
| `policy/sre_support_engineer.codexpolicy` | Execution policy for auto-allowing kubectl |
| `prompts/sre_support_engineer.md` | Custom prompt for SRE incident investigation |

## Configuration

### Customizing the Model

Edit `agent.toml` to change the model:

```toml
[profiles.sre_support_engineer]
model = "gpt-5.1"                      # Or any supported model
model_reasoning_effort = "medium"      # minimal, low, medium, high
```

### Custom API Endpoint

For custom/private API endpoints, uncomment and configure:

```toml
[model_providers.custom-openai]
name = "Custom OpenAI Endpoint"
base_url = "https://your-api-endpoint.example.com/v1"
env_key = "CUSTOM_API_KEY"
wire_api = "responses"

[profiles.sre_support_engineer]
model_provider = "custom-openai"
```

### Azure OpenAI

For Azure OpenAI, uncomment and configure:

```toml
[model_providers.azure]
name = "Azure OpenAI"
base_url = "https://YOUR_PROJECT.openai.azure.com/openai"
env_key = "AZURE_OPENAI_API_KEY"
query_params = { api-version = "2025-04-01-preview" }
wire_api = "responses"

[profiles.sre_support_engineer]
model_provider = "azure"
model = "your-deployment-name"
```

### Session Directory

Zero automatically creates a session directory structure:

```
session_dir/
├── code/           # Agent-written code
├── plans/          # Final action plans
├── traces/         # OTEL traces, stdout.log, persistence/
└── output.json     # Final diagnosis output
```

## Usage

After installation, run:

```bash
# Using Zero CLI (recommended)
python -m zero --session-dir /tmp/session --read-only-dir /path/to/incident-snapshot

# Or using codex directly
codex --profile sre_support_engineer

# With a specific incident directory
cd /path/to/incident-snapshot
codex --profile sre_support_engineer
```

The agent will:
1. Analyze Kubernetes snapshots and alerts
2. Identify entities involved in the incident
3. Determine contributing factors
4. Generate `output.json` with the diagnosis

## Output Format

The agent generates `output.json` with this structure:

```json
{
  "entities": [
    {
      "id": "pod/my-app-abc123",
      "contributing_factor": true,
      "reasoning": "Pod was OOMKilled due to memory limits",
      "evidence": "kubectl logs show OutOfMemory errors at 14:32:01"
    }
  ]
}
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | API key for default OpenAI provider |
| `OR_API_KEY` | API key for OpenRouter |
| `OPENAI_BASE_URL` | Override base URL for OpenAI provider |
| `AZURE_OPENAI_API_KEY` | API key for Azure OpenAI (if configured) |
| `ETE_API_KEY` | API key for ETE LiteLLM Proxy |
