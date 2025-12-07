"""
Command-line interface for Zero.

Handles argument parsing and orchestrates the Codex execution.
"""

import argparse
import os
import sys

from .config import ZeroConfig, load_tools_manifest
from .runner import CodexRunner


def list_available_tools(manifest_path: str | None = None) -> None:
    """List all available tools from the manifest."""
    manifest = load_tools_manifest(manifest_path)
    tools = manifest.get("tools", {})
    
    if not tools:
        print("No tools found in manifest.")
        return
    
    print("\nAvailable MCP Tools:")
    print("=" * 60)
    
    # Separate by type
    stdio_tools = []
    http_tools = []
    
    for name, config in tools.items():
        tool_type = config.get("type", "stdio")
        description = config.get("description", "No description")
        
        if tool_type == "http":
            http_tools.append((name, description, config))
        else:
            stdio_tools.append((name, description, config))
    
    if stdio_tools:
        print("\n📦 Command-line Tools (stdio):")
        print("-" * 40)
        for name, desc, config in stdio_tools:
            cmd = config.get("command", "python")
            args = config.get("args", [])
            print(f"  {name}")
            print(f"    Description: {desc}")
            print(f"    Command: {cmd} {' '.join(args)}")
            print()
    
    if http_tools:
        print("\n🌐 HTTP Tools:")
        print("-" * 40)
        for name, desc, config in http_tools:
            url = config.get("url", "")
            print(f"  {name}")
            print(f"    Description: {desc}")
            print(f"    URL: {url}")
            print()
    
    print("=" * 60)
    print(f"Total: {len(tools)} tools ({len(stdio_tools)} stdio, {len(http_tools)} http)")
    print("\nUsage: zero --tools <tool_name> [--tools <another_tool>] ...")


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="zero",
        description="Run Codex agent against incident snapshots for SRE investigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with session and read-only directories
  python -m zero --session-dir /tmp/session --read-only-dir /path/to/Scenario-1

  # Multiple read-only directories
  python -m zero --session-dir /tmp/session \\
    --read-only-dir /path/to/scenario \\
    --read-only-dir /path/to/shared-data

  # With custom model and API key
  python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \\
    --model "anthropic/claude-opus-4.5" \\
    --model-provider openrouter \\
    --api-key-env OR_API_KEY

  # With trace collection
  python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \\
    --collect-traces

  # List available MCP tools
  python -m zero --list-tools

  # Enable MCP tools for the session
  python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario \\
    --tools sre_utils --tools k8s_helpers

Environment Variables:
  OR_API_KEY          OpenRouter API key
  OPENAI_API_KEY      OpenAI API key
  ETE_API_KEY         ETE LiteLLM Proxy API key
  AZURE_OPENAI_KEY    Azure OpenAI API key
        """,
    )

    # Session directory (required, writable)
    parser.add_argument(
        "--session-dir",
        "-s",
        type=str,
        required=True,
        help="Path to session directory where agent can read/write. Will contain: ./code, ./plans, ./traces, output.json",
    )

    # Read-only directories (array)
    parser.add_argument(
        "--read-only-dir",
        "-r",
        action="append",
        default=[],
        help="Read-only directory for agent access (can be specified multiple times)",
    )

    # Session ID (optional identifier)
    parser.add_argument(
        "--session-id",
        type=str,
        default=os.environ.get("SESSION_ID", "1"),
        help="Session identifier for tracking (default: $SESSION_ID or '1')",
    )

    # Model configuration
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="anthropic/claude-opus-4.5",
        help="Model identifier (default: anthropic/claude-opus-4.5)",
    )
    parser.add_argument(
        "--model-provider",
        type=str,
        default="openrouter",
        choices=["openrouter", "openai", "azure", "ete", "custom"],
        help="Model provider (default: openrouter)",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default="high",
        choices=["minimal", "low", "medium", "high"],
        help="Model reasoning effort level (default: high)",
    )

    # API configuration
    parser.add_argument(
        "--api-key-env",
        type=str,
        help="Environment variable name containing the API key (e.g., OR_API_KEY)",
    )
    parser.add_argument(
        "--api-base-url",
        type=str,
        help="Custom API base URL (overrides provider default)",
    )

    # Config directory
    parser.add_argument(
        "--config-dir",
        type=str,
        help="Path to zero config directory (default: bundled config or auto-generated)",
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        help="Path to custom prompt/instructions file (overrides default SRE prompt)",
    )
    parser.add_argument(
        "--policy-file",
        type=str,
        help="Path to custom execution policy file",
    )

    # Profile configuration
    parser.add_argument(
        "--profile",
        type=str,
        default="sre_support_engineer",
        help="Codex profile to use (default: sre_support_engineer)",
    )

    # Execution options
    parser.add_argument(
        "--full-auto",
        action="store_true",
        default=True,
        help="Run in full-auto mode (default: True)",
    )
    parser.add_argument(
        "--no-full-auto",
        action="store_false",
        dest="full_auto",
        help="Disable full-auto mode",
    )
    parser.add_argument(
        "--sandbox-mode",
        type=str,
        default="workspace-write",
        choices=["workspace-write", "workspace-read", "off"],
        help="Sandbox mode for Codex (default: workspace-write)",
    )
    parser.add_argument(
        "--network-access",
        action="store_true",
        default=False,
        help="Allow network access in sandbox",
    )

    # Query/task configuration
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default="Analyze the incident snapshot in these directories: {snapshot_dirs}. Write the diagnosis to {output_path}",
        help="Task query to send to the agent (placeholders: {output_path}, {snapshot_dirs})",
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would be executed without running it",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean session directory before running (removes all contents and reinitializes git)",
    )

    # Tracing options
    parser.add_argument(
        "--collect-traces",
        action="store_true",
        default=False,
        help="Enable OpenTelemetry trace collection",
    )
    parser.add_argument(
        "--otel-port",
        type=int,
        default=4318,
        help="Port for OTEL collector (default: 4318)",
    )

    # MCP Tools options
    parser.add_argument(
        "--tools",
        "-t",
        action="append",
        default=[],
        help="Enable MCP tool by name (can be specified multiple times, e.g., --tools sre_utils --tools k8s_helpers)",
    )
    parser.add_argument(
        "--tools-manifest",
        type=str,
        help="Path to custom tools manifest.toml (default: sre_tools/manifest.toml)",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List available tools from the manifest and exit",
    )

    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parsed_args = parse_args(args)

    # Handle --list-tools flag
    if getattr(parsed_args, "list_tools", False):
        list_available_tools(getattr(parsed_args, "tools_manifest", None))
        return 0

    try:
        # Build configuration from arguments
        config = ZeroConfig.from_args(parsed_args)

        if parsed_args.verbose:
            print(f"Configuration:")
            print(f"  Model: {config.model}")
            print(f"  Provider: {config.model_provider}")
            print(f"  Session dir: {config.session_dir}")
            print(f"  Session ID: {config.session_id}")
            print(f"  Read-only dirs: {config.read_only_dirs}")
            print(f"  Config dir: {config.config_dir}")
            print(f"  Prompt file: {config.prompt_file}")
            if config.enabled_tools:
                print(f"  Enabled tools: {', '.join(config.enabled_tools)}")
            else:
                print(f"  Enabled tools: (none)")

        # Create runner
        runner = CodexRunner(config)

        # Run the session
        return runner.run_session(dry_run=parsed_args.dry_run)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if parsed_args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
