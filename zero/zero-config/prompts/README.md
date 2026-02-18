# Zero Prompt Configuration

This directory contains modular prompt configurations for the Zero SRE agent.

## Prompt Structure

The prompts are organized in a modular way to avoid duplication:

### Base Components

- **`sre_react_online_base.md`** - Shared investigation workflow, task definition, output format, and best practices
- **`data_sources/`** - Directory containing data source-specific documentation
  - **`clickhouse.md`** - ClickHouse-specific data schema and query patterns
  - **`instana.md`** - Instana APM-specific capabilities and query patterns
  - **`kubernetes.md`** - Kubernetes MCP operations and investigation patterns

### Prompt Variants

- **`sre_react_online.md`** - Uses ClickHouse + Kubernetes MCPs
  - MCP servers: `offline_incident_analysis`, `clickhouse`, `kubernetes`
  - Includes: `data_sources/clickhouse.md` + `data_sources/kubernetes.md` + `sre_react_online_base.md`

- **`sre_react_online_instana.md`** - Uses Instana + Kubernetes MCPs
  - MCP servers: `offline_incident_analysis`, `instana`, `kubernetes`
  - Includes: `data_sources/instana.md` + `data_sources/kubernetes.md` + `sre_react_online_base.md`

- **`sre_react_shell_investigation.md`** - SRE incident diagnosis from offline snapshots
  - MCP servers: `offline_incident_analysis`

- **`finops_linear_analyses_shell_investigation.md`** - FinOps cost anomaly investigation from offline snapshots
  - No MCP servers required (uses shell tools to analyze `anomaly.json` and `data.csv`)

## File Inclusion Syntax

Prompt files use `{{include: path/to/file.md}}` to reference shared content:

```markdown
---
mcp_servers:
  - offline_incident_analysis
  - clickhouse
  - kubernetes
---

{{include: data_sources/clickhouse.md}}
{{include: data_sources/kubernetes.md}}
{{include: sre_react_online_base.md}}
```

This modular approach keeps the prompts DRY (Don't Repeat Yourself) while supporting multiple observability backends.
