"""
ClickHouse MCP Server - Docker/Podman based.

The ClickHouse MCP server runs via Docker/Podman container using the official
Python mcp-clickhouse server. This avoids Python dependency conflicts with litellm[proxy].

NOTE: We use the official mcp-clickhouse (https://github.com/ClickHouse/mcp-clickhouse)
instead of Altinity MCP (https://github.com/Altinity/altinity-mcp) because Altinity MCP
does not support PROXY_PATH, which is required for ClickHouse instances behind reverse
proxies or load balancers with custom URL paths (e.g., AWS ELB with path-based routing).

Configuration is handled in zero/zero-config/config.toml:
  [mcp_servers.clickhouse]
  command = "podman"  # or "docker"
  args = [
    "run", "--rm", "-i",
    "-e", "CLICKHOUSE_HOST=${CLICKHOUSE_HOST}",
    "-e", "CLICKHOUSE_PORT=${CLICKHOUSE_PORT}",
    "-e", "CLICKHOUSE_USER=${CLICKHOUSE_USER}",
    "-e", "CLICKHOUSE_PASSWORD=${CLICKHOUSE_PASSWORD}",
    "-e", "PROXY_PATH=${CLICKHOUSE_PROXY_PATH}",
    "-e", "CLICKHOUSE_SECURE=${CLICKHOUSE_SECURE}",
    "-e", "CLICKHOUSE_VERIFY=${CLICKHOUSE_VERIFY}",
    "mcp/clickhouse:latest"
  ]

Environment variables (from .env):
  - CLICKHOUSE_HOST (hostname only, e.g., elb.amazonaws.com)
  - CLICKHOUSE_PORT (default: 8123 or 80 for HTTP)
  - CLICKHOUSE_USER (default: default)
  - CLICKHOUSE_PASSWORD (default: empty)
  - CLICKHOUSE_PROXY_PATH (for reverse proxy paths, e.g., /clickhouse/clickhouse)
  - CLICKHOUSE_SECURE (true/false for HTTPS, default: false)
  - CLICKHOUSE_VERIFY (true/false for SSL verification, default: true)

The PROXY_PATH variable enables connecting to ClickHouse servers behind reverse proxies
or load balancers with custom URL paths (e.g., AWS ELB with path-based routing).

See: https://github.com/ClickHouse/mcp-clickhouse
"""

__all__ = []
