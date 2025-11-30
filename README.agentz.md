# Agentz - Parameterized Codex Wrapper for SRE Investigation

Agentz is a Python module that provides a fully parameterized interface to run OpenAI Codex CLI against incident snapshots for SRE root cause analysis.

## Prerequisites

### Install Codex CLI

Agentz requires the Codex CLI to be installed and available in your PATH:

```bash
# Option 1: Using npm
npm install -g @openai/codex

# Option 2: Using Homebrew (macOS)
brew install codex

# Verify installation
codex --version
```

For more information, see the [Codex CLI documentation](https://github.com/openai/codex).

### API Key Setup

You'll need an API key for your chosen model provider:

```bash
# OpenRouter (default)
export OR_API_KEY="your-openrouter-api-key"

# OpenAI
export OPENAI_API_KEY="your-openai-api-key"

# Azure OpenAI
export AZURE_OPENAI_API_KEY="your-azure-api-key"

# ETE LiteLLM Proxy (internal)
export ETE_API_KEY="your-ete-api-key"
```

## Installation

The agentz module is part of the sre-support-agent package:

```bash
# Install from the repository
pip install -e .

# Or with uv
uv pip install -e .
```

## Quick Start

### Basic Usage

```bash
# Run against a single scenario
python -m agentz --scenario-dir /path/to/Scenario-1

# With custom run ID
python -m agentz --scenario-dir /path/to/Scenario-1 --run-id 42

# With a specific model
python -m agentz --scenario-dir /path/to/Scenario-1 \
  --model "anthropic/claude-opus-4.5" \
  --model-provider openrouter
```

### Run All Scenarios

```bash
# Run all Scenario-* directories in a base path
python -m agentz --scenarios-base-dir /path/to/snapshots --run-all

# Run a specific scenario by name
python -m agentz --scenarios-base-dir /path/to/snapshots --scenario-name Scenario-105
```

### Using the CLI Script

After installation, you can also use the `agentz` command directly:

```bash
agentz --scenario-dir /path/to/Scenario-1 --run-id 1
```

## Configuration Options

### Model Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--model`, `-m` | `anthropic/claude-opus-4.5` | Model identifier |
| `--model-provider` | `openrouter` | Provider: `openrouter`, `openai`, `azure`, `ete`, `custom` |
| `--reasoning-effort` | `high` | Reasoning level: `minimal`, `low`, `medium`, `high` |

### Output Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--run-id`, `-r` | `1` or `$RUN_ID` | Run identifier for output organization |
| `--output-dir`, `-o` | `/tmp/agentz-output/reports` | Base directory for output files |

### API Configuration

| Option | Description |
|--------|-------------|
| `--api-key-env` | Environment variable name for API key (auto-detected from provider) |
| `--api-base-url` | Custom API base URL (overrides provider default) |

### Custom Configuration

| Option | Description |
|--------|-------------|
| `--config-dir` | Path to custom agentz config directory |
| `--prompt-file` | Path to custom prompt/instructions file |
| `--policy-file` | Path to custom execution policy file |
| `--profile` | Codex profile name (default: `sre_support_engineer`) |

### Execution Options

| Option | Default | Description |
|--------|---------|-------------|
| `--full-auto` | `true` | Run in full-auto mode |
| `--no-full-auto` | | Disable full-auto mode |
| `--sandbox-mode` | `workspace-write` | Sandbox mode: `workspace-write`, `workspace-read`, `off` |
| `--network-access` | `false` | Allow network access in sandbox |
| `--writable-root` | | Additional writable directory (can be repeated) |

### Tracing Options

| Option | Default | Description |
|--------|---------|-------------|
| `--collect-traces` | `false` | Enable OpenTelemetry trace collection |
| `--traces-output-dir` | `{output_dir}/traces` | Directory for trace JSONL files |
| `--otel-port` | `4318` | Port for OTEL collector server |

### Other Options

| Option | Description |
|--------|-------------|
| `--query`, `-q` | Custom task query (use `{output_path}` as placeholder) |
| `--verbose`, `-v` | Enable verbose output |
| `--dry-run` | Print command without executing |

## Examples

### Example 1: Basic Investigation

```bash
python -m agentz \
  --scenario-dir /path/to/ITBench-Snapshots/snapshots/sre/v0.1/Scenario-1 \
  --run-id 1
```

### Example 2: Custom Model with OpenRouter

```bash
OR_API_KEY="sk-or-v1-xxx" python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --model "openai/gpt-4o" \
  --model-provider openrouter \
  --reasoning-effort high
```

### Example 3: Azure OpenAI

```bash
AZURE_OPENAI_API_KEY="xxx" python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --model "gpt-4" \
  --model-provider azure \
  --api-base-url "https://your-project.openai.azure.com/openai"
```

### Example 4: Custom Prompt

```bash
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --prompt-file ./my-custom-prompt.md
```

### Example 5: Batch Processing All Scenarios

```bash
python -m agentz \
  --scenarios-base-dir /path/to/ITBench-Snapshots/snapshots/sre/v0.1 \
  --run-all \
  --run-id batch-001 \
  --output-dir /data/results
```

### Example 6: Dry Run (Preview Command)

```bash
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --dry-run \
  --verbose
```

### Example 7: With Trace Collection

```bash
# Enable trace collection (requires otel-cli)
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --collect-traces \
  --verbose

# With custom traces output directory
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --collect-traces \
  --traces-output-dir /data/traces

# With custom OTEL port
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --collect-traces \
  --otel-port 4319
```

## Programmatic Usage

You can also use agentz as a library:

```python
from agentz import run, AgentZConfig, CodexRunner

# Simple usage
exit_code = run(
    scenario_dir="/path/to/Scenario-1",
    run_id="1",
    model="anthropic/claude-opus-4.5",
    model_provider="openrouter",
)

# Advanced usage with full control
from argparse import Namespace

args = Namespace(
    scenario_dir="/path/to/Scenario-1",
    scenarios_base_dir=None,
    run_id="1",
    model="anthropic/claude-opus-4.5",
    model_provider="openrouter",
    reasoning_effort="high",
    output_dir="/tmp/agentz-output/reports",
    config_dir=None,
    prompt_file=None,
    policy_file=None,
    profile="sre_support_engineer",
    full_auto=True,
    sandbox_mode="workspace-write",
    network_access=False,
    writable_root=[],
    query="analyze the incident snapshot in this directory. Write the agent_output.json file at {output_path}",
    verbose=True,
    api_key_env="OR_API_KEY",
    api_base_url=None,
)

config = AgentZConfig.from_args(args)
runner = CodexRunner(config)
exit_code = runner.run_scenario("/path/to/Scenario-1")
```

## Output

The agent generates an `agent_output.json` file with the diagnosis:

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

The output file is written to:
```
{output_dir}/{scenario_name}/{run_id}/agent_output.json
```

For example:
```
/tmp/agentz-output/reports/Scenario-1/1/agent_output.json
```

## Trace Collection

Agentz supports OpenTelemetry trace/log collection using `otel-cli`. When enabled, it captures all telemetry emitted by Codex during execution and writes them to JSONL files.

### Prerequisites

Install otel-cli:

```bash
brew install otel-cli
```

### Enable Tracing

```bash
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --collect-traces
```

### How It Works

When `--collect-traces` is enabled, agentz:

1. **Generates a temporary config.toml** with the correct OTEL settings pointing to the local collector
2. **Starts an `otel-cli server json` subprocess** before running Codex
3. The server listens on the configured port (default: 4318) for OTLP logs/traces
4. **Codex exports telemetry** to this local endpoint
5. All data is written to a JSONL file for the scenario
6. The server is stopped after Codex completes

### Auto-Generated OTEL Configuration

When `--collect-traces` is enabled, the generated config.toml automatically includes the OTEL section **at the root level** (this is required by Codex):

```toml
profile = "sre_support_engineer"

# OTEL must be at root level, NOT inside a profile
[otel]
environment = "dev"
log_user_prompt = true
exporter = { otlp-http = { endpoint = "http://localhost:4318/v1/logs", protocol = "binary" } }

[profiles.sre_support_engineer]
# ... profile config ...
```

The endpoint is automatically configured based on `--otel-port` (default: 4318).

**Important**: The `[otel]` section MUST be at the root level of config.toml, not nested inside a profile. Agentz handles this automatically.

### Trace Output

Traces are written to:
```
{traces_output_dir}/{scenario_name}/{run_id}/traces.jsonl
```

Default location:
```
/tmp/agentz-output/reports/traces/Scenario-1/1/traces.jsonl
```

### Programmatic Usage

```python
from agentz import OtelTraceCollector

# Use as context manager
with OtelTraceCollector(output_file="/tmp/traces.jsonl", verbose=True) as collector:
    # Run your code that emits traces
    print(f"Collector running at: {collector.get_endpoint()}")

# Or manual control
collector = OtelTraceCollector(output_file="/tmp/traces.jsonl")
collector.start()
# ... do work ...
collector.stop()
```

## Custom Configuration Directory

Agentz can use a custom configuration directory with:

```
my-config/
├── config.toml           # Main configuration
├── prompts/
│   └── my_profile.md     # Custom prompt
└── policy/
    └── my_profile.codexpolicy  # Execution policy
```

Then run with:

```bash
python -m agentz \
  --scenario-dir /path/to/Scenario-1 \
  --config-dir ./my-config \
  --profile my_profile
```

## Default Prompt

If no custom prompt is provided, agentz uses the default SRE investigation prompt:

> You are an SRE support agent and your task is to find out the root cause of the incidents. The data has been captured from a live kubernetes environment and available. Since it is a support case we do not have access to the live environment just the snapshots.
>
> You must explain the cause of all alerts. DONT WRITE ANY CODE OR REMOVE ANY CODE/DATA.
>
> You must identify all the entities that caused or were impacted by the incident and determine if it was a contributing factor or not.

## Default Execution Policy

The default policy auto-allows:
- `kubectl` read operations (get, describe, logs, top, etc.)
- File reading commands (cat, head, tail, ls, find, grep)

And forbids:
- Destructive kubectl operations (delete, apply, create, etc.)
- File modification commands (rm, mv)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OR_API_KEY` | OpenRouter API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `ETE_API_KEY` | ETE LiteLLM Proxy API key |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `RUN_ID` | Default run ID (used if `--run-id` not specified) |

## Troubleshooting

### Codex not found

```
RuntimeError: codex CLI not found in PATH
```

Install codex CLI:
```bash
npm install -g @openai/codex
# or
brew install codex
```

### API key not set

```
Warning: API key environment variable OR_API_KEY is not set
```

Export your API key:
```bash
export OR_API_KEY="your-api-key"
```

### Permission denied on output directory

Ensure the output directory is writable:
```bash
mkdir -p /tmp/agentz-output/reports
chmod 755 /tmp/agentz-output/reports
```

Or specify a different output directory:
```bash
python -m agentz --scenario-dir /path/to/Scenario-1 --output-dir ~/my-reports
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         agentz module                           │
├──────────────┬──────────────────┬──────────────────────────────┤
│    cli.py    │    config.py     │          runner.py           │
│              │                  │                              │
│  Argument    │  Configuration   │  Codex CLI                   │
│  Parsing     │  Management      │  Execution                   │
│              │  Path Resolution │                              │
└──────┬───────┴────────┬─────────┴──────────────┬───────────────┘
       │                │                        │
       ▼                ▼                        ▼
  Command Line    Dynamic Config         subprocess.run(codex)
     Args           Generation                    │
                       │                          │
                       ▼                          ▼
                  CODEX_HOME              agent_output.json
                  (temp or custom)
```

## Contributing

Contributions are welcome! Please ensure your changes:

1. Follow the existing code style
2. Include appropriate documentation
3. Pass any existing tests

