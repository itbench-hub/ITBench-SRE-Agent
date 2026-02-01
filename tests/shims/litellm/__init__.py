"""Test shim for litellm (moved from src -> tests/shims).

This file provides a minimal, test-only replacement for the `litellm`
package so containerized and CI tests can run offline without real
providers. It is intended to live under `ITBench-SRE-Agent/tests/shims`
and only be loaded when `LUMYN_TEST_SHIMS=1`.
"""
from __future__ import annotations
import json

class _Msg:
    def __init__(self, content: str):
        self.content = content
        # Minimal fields the code may access
        self.role = "assistant"
        # tool_calls used when a model returns a tool invocation
        self.tool_calls = []

class _Choice:
    def __init__(self, content: str):
        self.message = _Msg(content)
        # Provide finish_reason which production completions expose
        self.finish_reason = "stop"

class _Completion:
    def __init__(self, content: str):
        self.choices = [ _Choice(content) ]
        # Optional usage metadata
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def completion(**kwargs):
    """Return a fake completion object.

    When `tools` are provided this shim will simulate a tool-calling
    response (finish_reason == "tool_calls") and attach a minimal
    `message.tool_calls` structure so the code that expects function
    calling will work during tests.
    """
    provider = kwargs.get("model", "<no-model-provided>")

    tools = kwargs.get("tools")
    messages = kwargs.get("messages") or []
    full_text = " ".join([m.get("content", "") if isinstance(m, dict) else str(m) for m in messages])

    if tools:
        tool_def = tools[0]
        func_name = tool_def.get("function", {}).get("name", "unknown_function")
        params = tool_def.get("function", {}).get("parameters", {}).get("properties", {})
        required = tool_def.get("function", {}).get("parameters", {}).get("required", [])
        args = {}
        import re
        for p in required:
            if "topology" in p or "topology" in params.get(p, {}).get("description", ""):
                m = re.findall(r"\S+\.json", full_text)
                args[p] = m[-1] if m else "topology.json"
            elif "name" in p or "node_name" in p:
                if "front" in full_text.lower():
                    args[p] = "front-service"
                elif "back" in full_text.lower():
                    args[p] = "back-service"
                else:
                    args[p] = "example"
            elif "id" in p or "node_id" in p:
                if "front" in full_text.lower():
                    args[p] = "front-1"
                elif "back" in full_text.lower():
                    args[p] = "back-1"
                else:
                    args[p] = "node-1"
            else:
                args[p] = "example"

        class _ToolFunction:
            def __init__(self, name, arguments):
                self.name = name
                self.arguments = arguments

        class _ToolCall:
            def __init__(self, function):
                self.function = function

        func = _ToolFunction(func_name, json.dumps(args))
        tool_call = _ToolCall(func)

        comp = _Completion(f"[FAKE-TOOL-CALL for {func_name}]")
        comp.choices[0].finish_reason = "tool_calls"
        comp.choices[0].message.tool_calls = [tool_call]
        return comp

    if "kubectl" in full_text.lower() or "kubectl" in provider.lower():
        content = "```bash\nkubectl get namespaces\n```"
    else:
        content = f"[FAKE-COMPLETION for {provider}] fastest way: drive+plane (stub)"
    return _Completion(content)


__all__ = ["completion"]
