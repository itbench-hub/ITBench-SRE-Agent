# ISSUE - NO WAY TO HAVE BUDGET
codex doesn't currently have a built-in turn/iteration limit for full-auto mode. The available limits are: What exists:
stream_idle_timeout_ms - Connection timeout (default 5 min)
tool_output_token_limit - Limits token storage per tool output
model_auto_compact_token_limit - Context compaction threshold
Workarounds to prevent runaway tasks:
Use shell timeout to kill the process after N seconds:
timeout 300 codex exec --full-auto "..."  # 5 min limit
# or on macOS
gtimeout 300 codex exec --full-auto "..."
Wrap with a script that monitors output/iterations:
#!/bin/bash
MAX_RUNTIME=600  # 10 minutes
timeout $MAX_RUNTIME codex exec --full-auto "$@"
Use hooks to abort after certain conditions (requires code):
# In config - hooks can intercept tool calls
# but there's no built-in iteration counter
Feature request: A max_turns or max_tool_calls config option would be useful. This would be ~20-30 lines to implement in the core loop. Want me to add this feature to the codebase? Example config (if implemented):
[profiles.sre_support_engineer]
max_turns = 50           # Stop after 50 model responses
max_tool_calls = 100     # Stop after 100 tool executions
