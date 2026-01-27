"""
Instana MCP Server - Requires local Docker build.

IMPORTANT: Unlike ClickHouse MCP, Instana MCP does NOT provide pre-built Docker images.
You must build the Docker image locally from the official repository.

Why Docker? The Python package `pip install mcp-instana` conflicts with litellm[proxy]
(litellm requires rich==13.7.1, but mcp-instana requires rich>=13.9.4).

Building the Docker Image:
  The repository is included as a git submodule at: sre_tools/instana_mcp/mcp-instana

  1. Initialize and update the submodule (if not already done):
     git submodule update --init --recursive

  2. Build the Docker image:
     cd sre_tools/instana_mcp/mcp-instana
     podman build -t mcp-instana:latest .
     # (or: docker build -t mcp-instana:latest .)
     cd ../../..

  3. The image will be available locally as: mcp-instana:latest

Configuration in zero/zero-config/config.toml:
  [mcp_servers.instana]
  command = "podman"  # or "docker"
  args = [
    "run", "--rm", "-i",
    "-e", "INSTANA_BASE_URL=${INSTANA_BASE_URL}",
    "-e", "INSTANA_API_TOKEN=${INSTANA_API_TOKEN}",
    "mcp-instana:latest",
    "--transport", "stdio"
  ]

Environment variables (from .env):
  - INSTANA_BASE_URL (your Instana instance URL, e.g., https://example.instana.io)
  - INSTANA_API_TOKEN (your API token from Instana UI: Settings → API Tokens)

Docker image: mcp-instana:latest (must be built locally)
See: https://github.com/instana/mcp-instana
See: https://github.com/instana/mcp-instana/blob/main/DOCKER.md
"""

__all__ = []
