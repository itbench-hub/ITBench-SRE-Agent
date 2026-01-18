"""
Kubernetes MCP Server wrapper.

This module provides a conditional wrapper around the Kubernetes MCP server.
If kubernetes-mcp-server is installed, it will be used. Otherwise, a helpful error message is shown.
"""

try:
    from kubernetes_mcp_server import main

    # Re-export the main function
    __all__ = ["main"]
except ImportError as e:
    import sys

    def main():
        print(
            "Error: Kubernetes MCP server (kubernetes-mcp-server) is not installed.\n"
            "Install it with: uv sync --extra mcp-servers\n"
            "Or: uv pip install kubernetes-mcp-server",
            file=sys.stderr,
        )
        sys.exit(1)

    __all__ = ["main"]


if __name__ == "__main__":
    main()
