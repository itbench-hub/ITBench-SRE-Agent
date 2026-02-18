## Zero wrapper spec (Option C: minimal Codex wrapper)

### Context
`zero/` exists to run the Codex CLI reproducibly against incident snapshots with:

- **Workspace setup** (git init, config copy, AGENTS.md generation)
- **CODEX_HOME isolation** (ephemeral config that doesn't touch `~/.codex`)
- **Prompt variable substitution** (template variables → AGENTS.md)
- **Optional OTEL log capture** (Codex OTLP logs → JSONL for evaluation/debugging)

Everything else should be treated as **Codex's responsibility** and passed through.

This spec documents the design principles and requirements for **Option C**:

- Workspace setup (git init, copy config/prompts/policy)
- Prompt substitution and AGENTS.md generation
- Config generation with trust entry
- Trace collection
- Everything else passed through to `codex`

---

### Design principles
- **Codex is the source of truth**: Zero should not re-implement Codex CLI flags/semantics.
- **Thin waist**: Zero owns only the integration points Codex doesn't provide directly:
  - Setting up a trusted workspace with git repo
  - Copying bundled config/prompts/policy to workspace
  - Prompt variable substitution → AGENTS.md
  - Trace collection setup
- **No global side effects**: Zero MUST NOT modify the user's `~/.codex/config.toml`.
  - Zero MUST use `CODEX_HOME` pointing at the workspace directory.
- **Pass-through by default**:
  - Any argument not explicitly a Zero-only argument MUST be forwarded to Codex unchanged.
  - Zero MUST preserve Codex's own precedence rules (CLI flags override profile/root config, etc.).
- **Reproducibility**:
  - A given run with the same inputs should produce the same workspace layout and artifacts.
  - The config, prompts, and policies are copied to the workspace for auditing.
- **Safety**:
  - Only the workspace directory should be writable (via sandbox configuration).
  - Read-only directories should be used for context, never mutated.

---

### User-facing interface

#### Invocation
Zero MUST support a strict argument boundary between Zero args and Codex args:

- `zero [ZERO_ARGS...] -- [CODEX_ARGS...]`

Examples:

- Run with prompt template:
  - `zero --workspace /tmp/work --read-only-dir /path/to/Scenario-27 --prompt-file ./prompts/sre_react_shell_investigation.md --variable "SNAPSHOT_DIRS=- /path/to/Scenario-27" -- exec -m "openai/gpt-5.1"`
- Run with prompt template and additional user query:
  - `zero --workspace /tmp/work --prompt-file ./prompts/sre_react_shell_investigation.md --variable "SNAPSHOT_DIRS=- /path" -- exec -m "openai/gpt-5.1" "focus on cart service"`
- Run interactive TUI:
  - `zero --workspace /tmp/work --read-only-dir /path/to/Scenario-27 -- -m "openai/gpt-5.1"`
- Enable trace collection:
  - `zero --collect-traces --workspace /tmp/work --prompt-file ./prompts/sre_react_shell_investigation.md --variable "SNAPSHOT_DIRS=- /path" -- exec -m "openai/gpt-5.1"`

Rationale: avoids flag collisions and avoids Zero needing to "understand" Codex flags.

If `--` is omitted, Zero MAY treat remaining args as Zero-only args, but the preferred contract is that callers always include `--`.

#### Zero-only flags (minimal)
Zero MUST support the following minimal set of wrapper flags:

- `--workspace PATH` / `-w PATH` (required)
  - Writable workspace directory. Becomes `CODEX_HOME` and the working directory.
  - Zero will `git init` this directory if not already a git repo.
- `--read-only-dir PATH` / `-r PATH` (repeatable)
  - One or more data directories for read-only access.
- `--prompt-file PATH` (optional)
  - Prompt template file. When provided, Zero substitutes variables and writes to AGENTS.md.
- `--variable KEY=VALUE` / `-V KEY=VALUE` (repeatable)
  - Variable substitution for prompt template. Keys are normalized to uppercase.
- `--collect-traces`
  - Enable OTEL log capture (see tracing requirements).
- `--otel-port PORT` (optional, default `4318`)
  - Port for the local OTLP/HTTP receiver.
- `--verbose` / `-v`
  - Enable verbose output.
- `--dry-run`
  - Print command without executing.
- `--output-file NAME` (optional, default `agent_output.json`)
  - Expected output file name (exec mode only). Zero auto-retries if this file is not created.
- `--max-retries N` (optional, default `5`)
  - Maximum retry attempts if output file is not created (exec mode only).

All other behavior (model selection, profile, approval policy, sandbox mode, MCP enablement, etc.) MUST be provided by Codex args/config and therefore forwarded.

#### Reserved Codex flags
Zero MUST reject the following Codex flags with a clear error:

- `-C` / `--cd`: Zero controls the working directory via `--workspace`.
- `--json`: Zero always adds `--json` for `exec` mode.

If the user attempts to pass these flags after `--`, Zero MUST fail with an error message explaining why.

#### Codex args pass-through
- Everything after `--` MUST be executed as a Codex invocation.
- Zero MUST NOT validate or interpret those arguments (except for reserved flags above).
- Zero MUST forward the exit code from Codex.
- Zero MUST always add `--json` when the `exec` subcommand is detected.

---

### Prompt variable substitution

#### When `--prompt-file` is provided:
Zero MUST:

1. Read the prompt template file.
2. Substitute variables using `$VARNAME` format (uppercase, 2+ characters).
3. Validate that no unsubstituted `$VARNAME` placeholders remain.
4. Write the substituted content to `W/AGENTS.md`.
5. Codex automatically reads AGENTS.md for project instructions.

#### Variable format
- Variables use `$VARNAME` format (Codex-style).
- Variable names MUST be uppercase with 2+ characters.
- Single-character patterns like `$L$`, `$v$`, `$P$` are NOT treated as variables (LaTeX math support).

#### Auto-provided variables
Zero auto-provides only:

| Variable | Value |
|----------|-------|
| `$WORKSPACE_DIR` | Absolute path to workspace directory |

#### User-provided variables
All other variables MUST be provided via `--variable`:

```bash
--variable "SNAPSHOT_DIRS=- /path/to/scenario"
--variable "OUTPUT_PATH=/tmp/work/output.json"
```

#### Validation
If any `$VARNAME` (uppercase, 2+ chars) remains unsubstituted after processing, Zero MUST fail with an error listing the missing variables.

---

### Auto-retry for missing output (exec mode)

In `exec` mode, Zero implements automatic retry logic when the expected output file is not created.

#### Behavior
1. After Codex exits, Zero checks if `--output-file` (default: `agent_output.json`) exists in the workspace.
2. If the file is missing and retries remain, Zero re-runs Codex with:
   ```
   codex exec ... resume --last "I don't see <output-file>. Please resume the investigation and make sure to create the <output-file> file as instructed earlier."
   ```
3. This repeats up to `--max-retries` times (default: 5).
4. If the file is still missing after all retries, Zero exits with the last exit code.

#### Rationale
Agent runs may be interrupted or fail to complete the final output step. The `resume --last` feature in Codex allows continuing from the last state, which is more efficient than restarting from scratch.

#### Example
```bash
# Auto-retries up to 5 times if agent_output.json not created
zero --workspace /tmp/work \
    --prompt-file ./prompts/sre_react_shell_investigation.md \
    --variable "SNAPSHOT_DIRS=- /path/to/data" \
    -- exec --full-auto -m "openai/o4-mini"

# Custom output file and retry count
zero --workspace /tmp/work \
    --output-file output.json \
    --max-retries 3 \
    -- exec --full-auto -m "openai/o4-mini"
```

---

### Workspace layout requirements
Given `--workspace W`, Zero MUST ensure these paths exist:

- `W/.git/` (initialized if not present)
- `W/AGENTS.md` (generated from prompt template when `--prompt-file` is provided)
- `W/config.toml` (copied from `zero-config/config.toml` with modifications)
- `W/prompts/` (copied from `zero-config/prompts/`)
- `W/policy/` (copied from `zero-config/policy/`)
- `W/traces/` (for trace artifacts)
- `W/agent_output.json` (created by agent based on prompt instructions)

Zero MUST NOT preserve state between runs - each run copies fresh config files.

---

### Config setup requirements

#### Location and isolation
- Zero MUST set `CODEX_HOME` to the workspace directory.
- Zero MUST copy `zero-config/config.toml` to `W/config.toml`.
- Zero MUST copy `zero-config/prompts/` to `W/prompts/`.
- Zero MUST copy `zero-config/policy/` to `W/policy/`.

#### Config modifications
Zero MUST modify the copied `config.toml` to:

1. **Update `writable_roots`** to point only to the workspace directory.
2. **Add trust entry** for the workspace:
   ```toml
   [projects."<absolute workspace path>"]
   trust_level = "trusted"
   ```
3. **Update OTEL endpoint** if `--collect-traces` is set.

Note: `experimental_instructions_file` is NOT used because it's unreliable. Instead, Zero writes prompts to AGENTS.md which Codex reads automatically.

#### wire_api configuration
The bundled config MUST document the critical `wire_api` setting:

| Provider | Models | wire_api |
|----------|--------|----------|
| OpenAI (direct) | gpt-4o, gpt-5.1, o4-mini | `responses` |
| Azure OpenAI | gpt-4o, gpt-5.1 | `responses` |
| OpenRouter + OpenAI | openai/* | `responses` |
| OpenRouter + Anthropic | anthropic/* | `chat` |
| OpenRouter + Google | google/* | `chat` |
| Other providers | * | `chat` |

Using `wire_api = "responses"` with non-OpenAI models causes function calls to fail with empty arguments.

#### Codex assumptions satisfied
Zero's workspace setup satisfies the following Codex assumptions:

- **Git repo requirement**: Codex trusts directories with `.git/`. Zero initializes git if needed.
- **Project trust**: Custom instructions require the project to be trusted. Zero adds a `[projects.<path>].trust_level = "trusted"` entry.
- **CODEX_HOME**: Codex reads `config.toml` from `$CODEX_HOME`. Zero sets this to the workspace.
- **AGENTS.md**: Codex automatically reads `AGENTS.md` from the workspace for project instructions.

Reference: [Codex config docs](https://github.com/openai/codex/blob/main/docs/config.md)

---

### Trace collection requirements (`--collect-traces`)
When `--collect-traces` is set, Zero MUST:

1. Start a local OTLP/HTTP log receiver before launching Codex.
2. Update `[otel]` configuration in `config.toml` to point to `http://localhost:${otel_port}/v1/logs`.
3. Write received OTEL payloads as JSONL to:
   - `W/traces/traces.jsonl`
4. Capture Codex stdout/stderr into:
   - `W/traces/stdout.log`
5. On shutdown, stop the collector and ensure files are flushed.

---

### Non-goals
Under Option C, Zero MUST NOT:

- Recreate Codex's CLI flag surface area (model/provider/sandbox/approval/etc.)
- Maintain its own parallel "model/provider registry"
- Encode business logic that belongs in:
  - the prompt template
  - the Codex config file
  - the Codex CLI invocation
- Use `--session-dir` terminology (conflicts with Codex's `--session` concept)
- Use `experimental_instructions_file` (unreliable)

---

### Lessons learned

#### 1. experimental_instructions_file is unreliable
Codex's `experimental_instructions_file` config option doesn't work reliably across different scenarios. **Solution**: Write prompts to `AGENTS.md` which Codex reads automatically.

#### 2. wire_api must match the model provider
Using `wire_api = "responses"` with non-OpenAI models (Claude, Gemini, etc.) causes function calls to fail with empty arguments. **Solution**: Use `wire_api = "chat"` for non-OpenAI models.

#### 3. Profile-level config overrides are unreliable
Settings inside `[profiles.xxx]` don't reliably override `-c` flags. **Solution**: Use dedicated CLI flags (e.g., `-m` for model) which have highest precedence.

#### 4. LaTeX math in prompts
LaTeX expressions like `$L$`, `$v$`, `$P=1$` should not be treated as variables. **Solution**: Only match variables with 2+ uppercase characters (`$VARNAME`).

---

### Migration from v0.1
The following changes from Zero v0.1:

| Old | New |
|-----|-----|
| `--session-dir` | `--workspace` |
| Generates ephemeral config in temp dir | Copies bundled config to workspace |
| Runs from caller's CWD | Runs from workspace directory |
| Sets `-C <session-dir>` | Sets `cwd=workspace` and `CODEX_HOME=workspace` |
| N/A | Always adds `--json` for exec mode |
| N/A | Rejects `-C`/`--cd` and `--json` flags |
| Uses `experimental_instructions_file` | Writes to `AGENTS.md` |
| N/A | `--variable` flag for prompt substitution |
| Auto-provides multiple variables | Auto-provides only `$WORKSPACE_DIR` |

---

### References
- Codex docs (repository): `https://github.com/openai/codex/tree/main/docs`
- Codex config: `https://github.com/openai/codex/blob/main/docs/config.md`
- Codex prompts: `https://github.com/openai/codex/blob/main/docs/prompts.md`
- Codex exec (non-interactive): `https://github.com/openai/codex/blob/main/docs/exec.md`
- Codex advanced: `https://github.com/openai/codex/blob/main/docs/advanced.md`
