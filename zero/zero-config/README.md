# Zero Configuration

This directory contains bundled configuration files for Zero.

When you run Zero, these files are **copied to your workspace**:

- `config.toml` → `workspace/config.toml`
- `prompts/` → `workspace/prompts/`
- `policy/` → `workspace/policy/`

## Quick Start

**SRE Incident Diagnosis:**

```bash
# Basic exec mode with prompt template
python -m zero --workspace /tmp/work \
    --read-only-dir ./Scenario-1 \
    --prompt-file ./zero/zero-config/prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/Scenario-1" \
    -- exec -m "openai/gpt-5.1"

# With additional user query appended
python -m zero --workspace /tmp/work \
    --read-only-dir ./Scenario-1 \
    --prompt-file ./zero/zero-config/prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/Scenario-1" \
    -- exec -m "openai/gpt-5.1" "focus on the cart service"
```

**FinOps Cost Anomaly Investigation:**

```bash
# Run FinOps agent on a cost anomaly scenario
python -m zero --workspace /tmp/work-finops \
    --read-only-dir ./ITBench-Lite/snapshots/finops/v0.1-finops-anomaly/Scenario-1 \
    --prompt-file ./zero/zero-config/prompts/finops_linear_analyses_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/ITBench-Lite/snapshots/finops/v0.1-finops-anomaly/Scenario-1" \
    -- exec -m "openai/gpt-5.1" "Begin investigation"
```

**Other modes:**

```bash
# Interactive TUI mode (no prompt substitution)
python -m zero --workspace /tmp/work \
    --read-only-dir ./Scenario-1 \
    -- -m "openai/gpt-5.1"

# With trace collection
python -m zero --workspace /tmp/work \
    --read-only-dir ./Scenario-1 \
    --prompt-file ./prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/Scenario-1" \
    --collect-traces \
    -- exec -m "openai/gpt-5.1"
```

## What Zero Does

1. **Creates workspace** with proper structure
2. **Copies config** (`config.toml`) with modifications:
   - Updates `writable_roots` to workspace
   - Adds trust entry for workspace
3. **Copies prompts and policies** to workspace
4. **Initializes git** in workspace (Codex trusts git repos)
5. **Substitutes prompt variables** (when `--prompt-file` is provided)
6. **Writes AGENTS.md** with substituted prompt (Codex reads this automatically)
7. **Sets CODEX_HOME** to workspace directory
8. **Runs Codex** with pass-through arguments + user query

## Zero-only Flags

| Flag | Description |
|------|-------------|
| `--workspace PATH` / `-w PATH` | Workspace directory (required). Becomes CODEX_HOME and cwd. |
| `--read-only-dir PATH` / `-r PATH` | Read-only data directory (repeatable). |
| `--prompt-file PATH` | Prompt template file for variable substitution. |
| `--variable KEY=VALUE` / `-V KEY=VALUE` | Variable substitution (repeatable). Keys are uppercased. |
| `--output-file NAME` | Expected output file (exec mode). Auto-retries if missing. Default: `agent_output.json` |
| `--max-retries N` | Max retries if output file not created (exec mode). Default: `5` |
| `--collect-traces` | Enable OTEL trace collection. |
| `--otel-port PORT` | Port for OTEL collector (default: 4318). |
| `--verbose` / `-v` | Enable verbose output. |
| `--dry-run` | Print command without executing. |

## Prompt Variable Substitution

Zero supports Codex-style variable substitution using `$VARNAME` format.

### Auto-provided Variables

| Variable | Value |
|----------|-------|
| `$WORKSPACE_DIR` | Workspace directory path (auto-provided) |

### User-provided Variables

All other variables must be provided via `--variable`:

```bash
--variable "SNAPSHOT_DIRS=- /path/to/scenario"
--variable "OUTPUT_PATH=/tmp/work/output.json"
--variable "MY_CUSTOM_VAR=some value"
```

### Variable Format Rules

- Variables use `$VARNAME` format (uppercase, 2+ characters)
- LaTeX math expressions like `$L$`, `$v$`, `$P$` are **NOT** treated as variables
- If any `$VARNAME` remains unsubstituted, Zero fails with an error

### Example Prompt Template

```markdown
# My Agent Instructions

Analyze data in: $SNAPSHOT_DIRS

Working directory: $WORKSPACE_DIR

## Algorithm
Use status codes: $L=0$ (healthy), $L=1$ (broken)  ← LaTeX, not variables!
```

## Workspace Structure

After running Zero with `--prompt-file`:

```
workspace/
├── .git/           # Git repo (for Codex trust)
├── AGENTS.md       # ← Substituted prompt (Codex reads automatically!)
├── config.toml     # Codex configuration
├── prompts/        # Original prompt templates
├── policy/         # Execution policies
├── traces/         # OTEL traces, stdout logs
│   └── traces.jsonl
└── agent_output.json  # Agent output (created by agent)
```

## Reserved Flags

Zero **rejects** the following Codex flags:

| Flag | Reason |
|------|--------|
| `-C` / `--cd` | Zero controls working directory via `--workspace`. |
| `--json` | Zero always adds `--json` for `exec` mode. |

---

## Auto-Retry for Missing Output (Exec Mode)

In `exec` mode, Zero automatically retries if the expected output file is not created after Codex exits.

### How It Works

1. After Codex exits, Zero checks if `agent_output.json` (or custom `--output-file`) exists in the workspace
2. If the file is missing, Zero automatically re-runs Codex with:
   ```
   codex exec ... resume --last "I don't see agent_output.json file. Please resume the investigation and make sure to create the agent_output.json file as instructed earlier."
   ```
3. This repeats up to `--max-retries` times (default: 5)
4. If the file is still missing after all retries, Zero exits with the last exit code

### Example

```bash
# Default: checks for agent_output.json, retries up to 5 times
python -m zero --workspace /tmp/work \
    --prompt-file ./prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/data" \
    -- exec --full-auto -m "Azure/gpt-5.1"

# Custom output file and retry count
python -m zero --workspace /tmp/work \
    --output-file output.json \
    --max-retries 3 \
    --prompt-file ./prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/data" \
    -- exec --full-auto -m "openai/o4-mini"
```

### Verbose Output

With `--verbose`, Zero shows retry attempts:

```
⚠ Output file not found: agent_output.json. Retrying with 'resume --last' (4 retries left)...

============================================================
Attempt: 2/6
CODEX_HOME: /tmp/work
Working directory: /tmp/work
Command: ['codex', 'exec', '--json', '-m', 'openai/o4-mini', 'resume', '--last', "I don't see agent_output.json..."]
============================================================
```

---

## Model Provider Configuration

### ⚠️ IMPORTANT: wire_api Setting

**This is critical!** The `wire_api` setting must match the model provider:

| Provider | Models | wire_api |
|----------|--------|----------|
| OpenAI (direct) | gpt-4o, gpt-5.1, o4-mini | `responses` |
| Azure OpenAI | gpt-4o, gpt-5.1 | `responses` |
| OpenRouter + OpenAI models | openai/gpt-5.1, openai/o4-mini | `responses` |
| OpenRouter + Anthropic | anthropic/claude-opus-4.5 | `chat` ⚠️ |
| OpenRouter + Google | google/gemini-2.5-pro | `chat` ⚠️ |
| OpenRouter + Other | mistral/*, etc. | `chat` ⚠️ |

**If you use `wire_api = "responses"` with non-OpenAI models, function calls will fail with empty arguments!**

### Example Configurations

#### OpenRouter with OpenAI models (responses)
```toml
[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
env_key = "OR_API_KEY"
wire_api = "responses"  # OK for openai/* models
```

#### OpenRouter with Claude/Gemini (chat)
```toml
[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
env_key = "OR_API_KEY"
wire_api = "chat"  # Required for non-OpenAI models!
```

#### Azure OpenAI
```toml
[model_providers.azure]
name = "Azure OpenAI"
base_url = "https://YOUR_PROJECT.openai.azure.com/openai"
env_key = "AZURE_OPENAI_API_KEY"
query_params = { api-version = "2025-04-01-preview" }
wire_api = "responses"
```

### Customizing the Model

Pass via Codex CLI flags after `--`:

```bash
python -m zero --workspace /tmp/work \
    --prompt-file ./prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/data" \
    -- exec -m "openai/gpt-5.1" "investigate"
```

---

## Lessons Learned & Troubleshooting

### 1. `experimental_instructions_file` is Unreliable

**Problem**: Codex's `experimental_instructions_file` config option doesn't work reliably.

**Solution**: Zero writes the substituted prompt to `AGENTS.md` instead. Codex automatically reads `AGENTS.md` from the workspace.

### 2. Function Calls Fail with Empty Arguments

**Symptom**: 
```json
{"type":"function_call","name":"shell","arguments":""}
"failed to parse function arguments: Error(\"EOF while parsing a value\"..."
```

**Cause**: Using `wire_api = "responses"` with non-OpenAI models (Claude, Gemini, etc.)

**Solution**: Set `wire_api = "chat"` for non-OpenAI models.

### 3. Profile-level Config Overrides Don't Work

**Problem**: Settings inside `[profiles.xxx]` don't override `-c` flags reliably.

**Solution**: Use the dedicated CLI flags (e.g., `-m` for model) which have highest precedence.

### 4. Long Prompts Work Fine

Long prompts (9KB+) passed via command-line arguments work correctly when using `subprocess.Popen` with a list (no shell escaping needed).

### 5. LaTeX in Prompts

LaTeX math expressions like `$L$`, `$v$`, `$P=1$` are safely ignored because Zero only matches variables with 2+ uppercase characters (`$VARNAME`).

---

## Output Format

The agent generates `agent_output.json` with this structure:

```json
{
  "entities": [
    {
      "id": "Kind/name uid <kubernetes-uid>",
      "contributing_factor": true,
      "reasoning": "Short explanation (max 2 sentences)",
      "evidence": "Summary of alerts/events/logs/traces/metrics"
    }
  ],
  "alerts_explained": [
    {
      "alert": "<alert name>",
      "explanation": "Why this alert fired (max 2 sentences)",
      "explained": true
    }
  ]
}
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OR_API_KEY` | API key for OpenRouter |
| `OPENAI_API_KEY` | API key for OpenAI |
| `AZURE_OPENAI_API_KEY` | API key for Azure OpenAI |
| `ETE_API_KEY` | API key for ETE LiteLLM Proxy |

---

## References

- [Codex config docs](https://github.com/openai/codex/blob/main/docs/config.md)
- [Codex prompts docs](https://github.com/openai/codex/blob/main/docs/prompts.md)
- [Codex exec (non-interactive)](https://github.com/openai/codex/blob/main/docs/exec.md)
- [Codex advanced](https://github.com/openai/codex/blob/main/docs/advanced.md)
