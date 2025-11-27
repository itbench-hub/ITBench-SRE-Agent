"""
Main entry point for the SRE Support Agent.

This module handles CLI argument parsing and runs the investigation loop,
streaming results to the console as the agent works.
"""

import argparse
import asyncio
import json
import os

from .config import AgentConfig
from .graph import create_graph, generate_diagnosis


def parse_args():
    parser = argparse.ArgumentParser(
        description="SRE Support Agent - AI-powered incident diagnosis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m sre_support_agent "Diagnose the incident"
  python -m sre_support_agent --dir ./snapshots/Scenario-3 "Investigate alerts"
  python -m sre_support_agent --dir /path/to/scenario --config custom.toml
        """,
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="An alert has fired in the cluster. Diagnose the incident.",
        help="The investigation query (default: diagnose incident)",
    )
    parser.add_argument(
        "--dir", "-d",
        dest="base_dir",
        help="Directory containing snapshot data (overrides config)",
    )
    parser.add_argument(
        "--config", "-c",
        dest="config_path",
        help="Path to config file (default: agent.toml)",
    )
    return parser.parse_args()


def is_valid_diagnosis(content: str) -> bool:
    """Check if the response looks like a valid diagnosis (contains entities JSON)."""
    if not content or len(content.strip()) < 20:
        return False
    
    has_entities = '"entities"' in content or "'entities'" in content
    has_json_structure = "{" in content and "}" in content
    
    looks_like_file = content.strip().startswith("---") or "Function:" in content[:50]
    looks_like_tool_output = content.strip().startswith("FILE:") or content.strip().startswith("DIR:")
    
    if looks_like_file or looks_like_tool_output:
        return False
    
    return has_entities or (has_json_structure and len(content) > 100)


def format_tool_call(tool_call: dict) -> str:
    """Format a tool call for display."""
    func = tool_call.get("function", {})
    tool_name = func.get("name", "unknown")
    
    try:
        args = json.loads(func.get("arguments", "{}"))
    except json.JSONDecodeError:
        args = {}
    
    arg_str = " ".join([
        f'{k}="{v}"' if isinstance(v, str) else f'{k}={v}' 
        for k, v in args.items()
    ])
    return f"{tool_name}({arg_str})"


async def main():
    """Main entry point for the SRE Support Agent."""
    args = parse_args()

    # Find config file
    if args.config_path:
        config_path = args.config_path if os.path.exists(args.config_path) else None
    else:
        possible_paths = ["agent.toml", "agents/sre/agent.toml"]
        config_path = None
        for path in possible_paths:
            if os.path.exists(path):
                config_path = path
                break

    if config_path:
        print(f"Loading configuration from {config_path}")
        config = AgentConfig.from_toml(config_path)
    else:
        print("Configuration file not found, using defaults.")
        config = AgentConfig()

    # Override base_dir if provided via command line
    if args.base_dir:
        config.file_tools.base_dir = args.base_dir

    print("Initializing SRE Support Agent...")

    # Set environment variables for litellm
    if config.llm_config.api_key:
        os.environ["OPENAI_API_KEY"] = config.llm_config.api_key
    if config.llm_config.base_url:
        os.environ["OPENAI_API_BASE"] = config.llm_config.base_url
        os.environ["OPENAI_BASE_URL"] = config.llm_config.base_url

    agent = create_graph(config)

    user_query = args.query
    full_query = f"""
    Investigate the incident in directory: {config.file_tools.base_dir}
    
    User Query: {user_query}
    """

    print(f"\n{'='*60}")
    print(f"📂 Investigating: {config.file_tools.base_dir}")
    print(f"❓ Query: {user_query}")
    print(f"{'='*60}\n")

    graph_config = {"recursion_limit": config.recursion_limit}

    step_count = 0
    collected_messages = [{"role": "user", "content": full_query}]
    hit_limit = False
    limit_type = ""
    malformed_response = False

    # Initial message in dict format
    initial_message = {"role": "user", "content": full_query}

    try:
        async for event in agent.astream({"messages": [initial_message]}, config=graph_config):
            for key, value in event.items():
                if key == "agent":
                    if "messages" in value and value["messages"]:
                        last_msg = value["messages"][-1]
                        collected_messages.append(last_msg)

                        # Check if it's an assistant message
                        if last_msg.get("role") == "assistant":
                            tool_calls = last_msg.get("tool_calls", [])
                            content = last_msg.get("content", "")
                            
                            if tool_calls:
                                # Has tool calls - print them
                                for tc in tool_calls:
                                    print(f"\n🔧 Calling: {format_tool_call(tc)}")
                                
                                if content:
                                    print(f"💭 {content}")
                            else:
                                # No tool calls - check if it's a valid diagnosis
                                if is_valid_diagnosis(content):
                                    print(f"\n{'='*60}")
                                    print("📋 FINAL DIAGNOSIS:")
                                    print(f"{'='*60}")
                                    print(content)
                                else:
                                    # Malformed response
                                    print(f"\n{'!'*60}")
                                    print("⚠️  MALFORMED RESPONSE DETECTED")
                                    print(f"{'!'*60}")
                                    print(f"Model output doesn't look like a valid diagnosis.")
                                    print(f"Raw output: {content[:1000]}...")
                                    malformed_response = True

                elif key == "tools":
                    step_count += 1
                    if "messages" in value and value["messages"]:
                        for msg in value["messages"]:
                            collected_messages.append(msg)

                            # Check if it's a tool response
                            if msg.get("role") == "tool":
                                content = msg.get("content", "")

                                if "[ALERTS]" in content:
                                    print(f"\n🚨 Step {step_count} | ALERTS:")
                                    for line in content.split("\n"):
                                        print(f"   {line}")
                                elif "[SUMMARY]" in content:
                                    print(f"\n📊 Step {step_count} | Summary:")
                                    print(f"   {content}")
                                elif "Investigation Progress" in content:
                                    print(f"\n📋 Todo Update:")
                                    print(content)
                                else:
                                    print(f"\n📊 Step {step_count} | Tool Result:")
                                    lines = content.split("\n")
                                    for line in lines[:20]:
                                        print(f"   {line}")
                                    if len(lines) > 20:
                                        print(f"   ... [{len(lines) - 20} more lines]")

    except Exception as e:
        error_str = str(e).lower()

        if "recursion" in error_str or "recursionlimit" in error_str:
            hit_limit = True
            limit_type = "RECURSION_LIMIT"
        elif "too long" in error_str or "context" in error_str or "token" in error_str or "input" in error_str:
            hit_limit = True
            limit_type = "CONTEXT_LIMIT"
        else:
            hit_limit = True
            limit_type = "ERROR"

        print(f"\n{'!'*60}")
        print(f"⚠️  {limit_type} REACHED")
        print(f"{'!'*60}")
        print(f"Steps completed: {step_count}")
        print(f"Error: {str(e)}")

    # Generate diagnosis if we hit a limit OR got a malformed response
    if hit_limit or malformed_response:
        print(f"\n🔄 Generating diagnosis from evidence gathered so far...\n")
        diagnosis = generate_diagnosis(config, collected_messages)
        print(f"\n{'='*60}")
        reason = limit_type if hit_limit else "MALFORMED_RESPONSE"
        print(f"📋 DIAGNOSIS (recovered - {reason})")
        print(f"{'='*60}")
        print(diagnosis)

    print(f"\n{'='*60}")
    print(f"✅ Investigation complete. Total steps: {step_count}")
    if hit_limit:
        print(f"⚠️  Note: Investigation was limited due to {limit_type}")
    if malformed_response:
        print(f"⚠️  Note: Model produced malformed output, diagnosis was regenerated")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
