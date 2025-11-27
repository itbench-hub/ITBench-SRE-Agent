"""
SRE Investigation Graph with Context-Aware Tool Output Summarization

This module implements a LangGraph-based agent that uses litellm directly for
LLM calls, providing broad model provider compatibility (OpenAI, Anthropic,
Google, Azure, etc.).

Key design decisions:
1. Uses litellm.completion() directly for all LLM calls
2. Uses plain dicts for messages (OpenAI/litellm format) - no LangChain message types
3. Supports tool calling with automatic summarization of large outputs

Summarization rules:
- list_directory: NEVER summarized (agent needs full listing)
- Alert files: NEVER summarized (agent must read completely)  
- Todo updates: NEVER summarized
- [NO_SUMMARIZE] prefix: NEVER summarized (explicit opt-out)
- Other large files: Summarized with investigation context
"""

import json
import operator
from typing import Annotated, Literal, Sequence, TypedDict

import litellm
from langgraph.graph import END, START, StateGraph

from .config import AgentConfig
from .langchain_tools import NO_SUMMARIZE_PREFIX, get_tools_list
from .prompts import DIAGNOSIS_PROMPT, SRE_REACT_PROMPT, TOOL_SUMMARIZER_PROMPT


class AgentState(TypedDict):
    """State for the SRE investigation agent. Messages are in OpenAI/litellm format."""
    messages: Annotated[Sequence[dict], operator.add]


def extract_evidence_summary(messages: Sequence[dict]) -> str:
    """Extract key findings from the conversation for diagnosis."""
    evidence_parts = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        
        if role == "tool":
            # Strip NO_SUMMARIZE prefix if present
            if content.startswith(NO_SUMMARIZE_PREFIX):
                content = content[len(NO_SUMMARIZE_PREFIX):].lstrip()

            if len(content) < 20:
                continue

            if "[ALERTS]" in content:
                evidence_parts.append(f"ALERTS:\n{content}")
            elif "[SUMMARY]" in content:
                evidence_parts.append(f"tool: {content}")
            elif "Investigation Progress" not in content:
                if len(content) < 500:
                    evidence_parts.append(f"tool: {content[:300]}")

        elif role == "assistant" and content:
            # Only include non-tool-call responses
            if "tool_calls" not in msg or not msg["tool_calls"]:
                if len(content) > 50:
                    evidence_parts.append(f"Analysis: {content[:500]}")

    return "\n\n---\n\n".join(evidence_parts[-15:])


def _convert_tools_to_litellm(tools: list) -> list[dict]:
    """Convert LangChain tools to litellm/OpenAI format."""
    result = []
    for tool in tools:
        # Get the schema from the tool
        if hasattr(tool, "args_schema") and tool.args_schema:
            schema = tool.args_schema.schema()
            # Remove title if present
            schema.pop("title", None)
        else:
            schema = {"type": "object", "properties": {}}
        
        result.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            },
        })
    return result


def create_graph(config: AgentConfig = None):
    if config is None:
        config = AgentConfig()

    # Get tools as LangChain tools (for execution) and convert to litellm format (for API)
    lc_tools = get_tools_list(config)
    tools_by_name = {tool.name: tool for tool in lc_tools}
    litellm_tools = _convert_tools_to_litellm(lc_tools)

    def get_investigation_context(messages: Sequence[dict]) -> str:
        """Extract context from recent messages for summarization."""
        context_parts = []
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")[:200]
                context_parts.append(f"Investigation: {content}")
                break

        recent_thoughts = []
        for msg in reversed(messages[-10:]):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if content:
                    recent_thoughts.insert(0, content[:150])
                    if len(recent_thoughts) >= 2:
                        break

        if recent_thoughts:
            context_parts.append(f"Recent focus: {' -> '.join(recent_thoughts)}")

        return "\n".join(context_parts) if context_parts else "General incident investigation"

    def is_alert_file(content: str) -> bool:
        """Check if content looks like alert data that shouldn't be summarized."""
        alert_indicators = [
            "alerts_in_alerting", "alerts_at_", '"alertname"',
            '"state":"firing"', '"state":"alerting"', "RequestErrorRate", "HighLatency",
        ]
        return any(indicator in content for indicator in alert_indicators)

    def is_directory_listing(content: str) -> bool:
        """Check if content is a directory listing."""
        return (
            content.startswith("FILE:") or 
            content.startswith("DIR:") or 
            "\nFILE:" in content or 
            "\nDIR:" in content
        )

    def should_skip_summarization(tool_name: str, content: str) -> bool:
        """Check if summarization should be skipped for this content."""
        if content.startswith(NO_SUMMARIZE_PREFIX):
            return True
        if tool_name == "list_directory" or is_directory_listing(content):
            return True
        if is_alert_file(content):
            return True
        if len(content) < 500 or "Investigation Progress" in content:
            return True
        return False

    def summarize_content(tool_name: str, content: str, context: str) -> str | None:
        """Summarize content using litellm. Returns None if should not be summarized."""
        if should_skip_summarization(tool_name, content):
            return None

        try:
            prompt = TOOL_SUMMARIZER_PROMPT.format(context=context, output=content[:3000])
            response = litellm.completion(
                model=config.model_name,
                api_key=config.llm_config.api_key,
                base_url=config.llm_config.base_url,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return f"[SUMMARY] {response.choices[0].message.content.strip()}"
        except Exception:
            return f"{content[:500]}\n[...truncated]"

    def agent_node(state: AgentState) -> dict:
        """Call the LLM and return the assistant message."""
        messages = list(state["messages"])
        
        # Check for retry condition (last message was malformed output from agent)
        if len(messages) > 1 and messages[-1].get("role") == "assistant":
            # Check if it was a non-tool-call, non-diagnosis response
            last_msg = messages[-1]
            if not last_msg.get("tool_calls") and not is_valid_diagnosis(last_msg.get("content", "")):
                messages.append({
                    "role": "system",
                    "content": "⚠️ YOUR LAST RESPONSE WAS MALFORMED.\n"
                               "You outputted raw text instead of a valid tool call or diagnosis JSON.\n"
                               "Please RETRY by calling a tool OR outputting the final diagnosis JSON."
                })
        
        # Ensure system prompt is first
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": SRE_REACT_PROMPT}] + messages

        # Call litellm
        response = litellm.completion(
            model=config.model_name,
            api_key=config.llm_config.api_key,
            base_url=config.llm_config.base_url,
            messages=messages,
            tools=litellm_tools,
        )

        assistant_message = response.choices[0].message
        
        # Build the response dict
        result = {
            "role": "assistant",
            "content": assistant_message.content or "",
        }
        
        # Add tool calls if present
        if hasattr(assistant_message, "tool_calls") and assistant_message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ]
        
        # Preserve thinking_blocks if present (for Gemini 3 compatibility)
        if hasattr(assistant_message, "thinking_blocks") and assistant_message.thinking_blocks:
            result["thinking_blocks"] = [
                {
                    "type": tb.get("type", "thinking") if isinstance(tb, dict) else getattr(tb, "type", "thinking"),
                    "thinking": tb.get("thinking", "") if isinstance(tb, dict) else getattr(tb, "thinking", ""),
                    "signature": tb.get("signature", "") if isinstance(tb, dict) else getattr(tb, "signature", ""),
                }
                for tb in assistant_message.thinking_blocks
            ]

        return {"messages": [result]}

    def is_valid_diagnosis(content: str) -> bool:
        """Check if the response looks like a valid diagnosis."""
        if not content or len(content.strip()) < 20:
            return False
        
        has_entities = '"entities"' in content or "'entities'" in content
        looks_like_file = content.strip().startswith("---") or "Function:" in content[:50]
        looks_like_tool_output = content.strip().startswith("FILE:") or content.strip().startswith("DIR:")
        
        if looks_like_file or looks_like_tool_output:
            return False
        
        return has_entities

    def should_continue(state: AgentState) -> Literal["tools", "agent", "end"]:
        """Determine the next step based on the last message."""
        messages = state["messages"]
        last_message = messages[-1]
        
        # If it has tool calls, continue to tools
        if last_message.get("tool_calls"):
            return "tools"
        
        # If it's a valid diagnosis, end
        content = last_message.get("content", "")
        if is_valid_diagnosis(content):
            return "end"
            
        # Otherwise retry (malformed response)
        return "agent"

    def tools_node(state: AgentState) -> dict:
        """Execute tools and return tool response messages."""
        messages = state["messages"]
        last_message = messages[-1]
        context = get_investigation_context(messages)

        tool_calls = last_message.get("tool_calls", [])
        if not tool_calls:
            return {"messages": []}

        tool_messages = []

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_id = tool_call["id"]
            
            # Parse arguments
            try:
                tool_args = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            # Execute the tool
            tool = tools_by_name.get(tool_name)
            if tool:
                try:
                    result = tool.invoke(tool_args)
                except Exception as e:
                    result = f"Error executing {tool_name}: {str(e)}"
            else:
                result = f"Unknown tool: {tool_name}"

            # Process the result (summarization, etc.)
            original_content = str(result)
            
            if original_content.startswith(NO_SUMMARIZE_PREFIX):
                clean_content = original_content[len(NO_SUMMARIZE_PREFIX):].lstrip()
            else:
                summary = summarize_content(tool_name, original_content, context)
                clean_content = summary if summary else original_content

            # Create tool response message
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": clean_content,
            })

        return {"messages": tool_messages}

    # Build the graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)

    workflow.add_edge(START, "agent")
    
    workflow.add_conditional_edges(
        "agent", 
        should_continue, 
        {
            "tools": "tools", 
            "end": END,
            "agent": "agent",
        }
    )
    
    workflow.add_edge("tools", "agent")

    return workflow.compile()


def generate_diagnosis(config: AgentConfig, messages: list) -> str:
    """Generate diagnosis from collected messages using DIAGNOSIS_PROMPT."""
    evidence = extract_evidence_summary(messages)

    if not evidence:
        return json.dumps({"entities": [], "note": "No evidence collected"})

    try:
        prompt = DIAGNOSIS_PROMPT.format(evidence=evidence)
        response = litellm.completion(
            model=config.model_name,
            api_key=config.llm_config.api_key,
            base_url=config.llm_config.base_url,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content
    except Exception as e:
        return json.dumps({"entities": [], "error": str(e)})
