# Agentz Configuration

This directory contains configuration files for the `sre_support_engineer` profile.

## Quick Start

```bash
# Use agentz-config directory directly as CODEX_HOME
export CODEX_HOME=/path/to/agentz-config

# Run with the profile
codex --profile sre_support_engineer "analyze the incident"

# Or one-liner
CODEX_HOME=./agentz-config codex exec "analyze the incident"
```

## Summary

| Method | Command |
|--------|---------|
| **CODEX_HOME** | `CODEX_HOME=./agentz-config codex exec "task"` |
| **CLI flags** | `codex exec -c 'model="o3"' -c 'model_reasoning_effort="high"' "task"` |
| **Copy to ~/.codex** | Traditional installation (see Option B below) |

The `agentz-config/` directory is fully portable - just set `CODEX_HOME` to point to it and everything (config, prompts, policies) will be loaded from there.

## Installation

### Option A: Use as standalone CODEX_HOME (Recommended)

Use this directory directly without copying:

```bash
# Set CODEX_HOME to point to this directory
export CODEX_HOME=/path/to/agentz-config

# Run codex - it will use all config from this directory
codex --profile sre_support_engineer "analyze the incident"

# Or with codex exec
codex exec --profile sre_support_engineer "analyze the incident"
```

### Option B: Copy to ~/.codex

Copy the files to your default Codex home directory:

```bash
# Create directories
mkdir -p ~/.codex/policy ~/.codex/prompts /tmp/agentz-output

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
- Outputs diagnosis to `agent_output.json`
- Additional writable directory for output storage

### Files

| File | Purpose |
|------|---------|
| `config.toml` | Main config with the sre_support_engineer profile |
| `policy/sre_support_engineer.codexpolicy` | Execution policy for auto-allowing kubectl |
| `prompts/sre_support_engineer.md` | Custom prompt for SRE incident investigation |

## Configuration

### Customizing the Model

Edit `config.toml` to change the model:

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

### Output Directory

Configure where output files are written:

```toml
[profiles.sre_support_engineer.sandbox_workspace_write]
writable_roots = [
    "/tmp/agentz-output",
    "/path/to/your/incident-reports",
]
```

## Usage

After installation, run:

```bash
# Using agentz (if built)
agentz --profile sre_support_engineer

# Or using codex
codex --profile sre_support_engineer

# With a specific incident directory
cd /path/to/incident-snapshot
codex --profile sre_support_engineer
```

The agent will:
1. Analyze Kubernetes snapshots and alerts
2. Identify entities involved in the incident
3. Determine contributing factors
4. Generate `agent_output.json` with the diagnosis

## Output Format

The agent generates `agent_output.json` with this structure:

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
| `OPENAI_BASE_URL` | Override base URL for OpenAI provider |
| `AZURE_OPENAI_API_KEY` | API key for Azure OpenAI (if configured) |
| `CUSTOM_API_KEY` | API key for custom provider (if configured) |
