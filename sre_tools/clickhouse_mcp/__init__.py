"""
ClickHouse MCP Server - Docker/Podman based.

The ClickHouse MCP server runs via Docker/Podman container using Altinity MCP.
This avoids Python dependency conflicts with litellm[proxy].

Configuration is handled in zero/zero-config/config.toml:
  [mcp_servers.clickhouse]
  command = "docker"
  args = ["run", "--rm", "-i", "--network=host", "ghcr.io/altinity/altinity-mcp:latest", ...]

Environment variables (from .env):
  - CLICKHOUSE_HOST
  - CLICKHOUSE_PORT (optional, defaults to 8123)
  - CLICKHOUSE_USER (optional, defaults to "default")
  - CLICKHOUSE_PASSWORD (optional, defaults to empty)

See: https://github.com/Altinity/altinity-mcp
"""

__all__ = []
