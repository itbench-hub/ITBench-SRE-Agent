"""
Offline Incident Analysis MCP Server entry point.

Run with: python -m sre_tools.offline_incident_analysis
"""

import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .tools import register_tools


async def run_server():
    """Run the MCP server."""
    app = Server("offline_incident_analysis")
    register_tools(app)

    # stdio_server is an async context manager
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    """Main entry point for the Offline Incident Analysis MCP server."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import sys
        print(f"Error starting MCP server: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
