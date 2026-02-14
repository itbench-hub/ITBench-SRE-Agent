"""
Analysis implementation.
"""

import ast
import csv
import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import numpy as np
    import pandas as pd
except ImportError:
    pd = None
    np = None

try:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig
except ImportError:
    TemplateMiner = None
    TemplateMinerConfig = None
    MaskingInstruction = None

from mcp.types import TextContent, Tool

from sre_tools.utils import format_timestamp, read_json_file, read_tsv_file, truncate_string

from ..shared import _parse_k8_object_identifier, _parse_time, _to_utc_timestamp


async def _log_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze application logs from OTEL log files with LOG PATTERN MINING.

    Supports:
    - Pattern analysis using logmine (default: enabled)
    - Time window filtering (start_time, end_time)
    - Entity filtering (k8_object in Kind/name format)
    - Service name filtering
    - Severity filtering (ERROR, WARNING, INFO, etc.)
    - Body text search
    - Pagination (offset, limit) for raw log mode
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    logs_file = args.get("logs_file", "")
    k8_object = args.get("k8_object")
    service_name = args.get("service_name")
    severity_filter = args.get("severity_filter")
    body_contains = args.get("body_contains")
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")

    # Pattern analysis parameters
    pattern_analysis = args.get("pattern_analysis", True)
    max_patterns = args.get("max_patterns", 50)
    similarity_threshold = args.get("similarity_threshold", 0.5)

    # Pagination parameters (for raw log mode)
    limit = args.get("limit", 100)
    offset = args.get("offset", 0)

    # limit=0 means no limit
    if limit == 0:
        limit = None

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    if not Path(logs_file).exists():
        return [TextContent(type="text", text=f"Logs file not found: {logs_file}")]

    try:
        df = pd.read_csv(logs_file, sep="\t")
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading logs file: {e}")]

    if df.empty:
        return [
            TextContent(
                type="text",
                text=json.dumps({"total_count": 0, "patterns" if pattern_analysis else "data": []}, indent=2),
            )
        ]

    # Parse ResourceAttributes to extract k8s metadata
    def extract_k8s_metadata(resource_attrs_str):
        """Extract k8s metadata from ResourceAttributes string."""
        try:
            if pd.isna(resource_attrs_str) or not resource_attrs_str:
                return {}
            attrs_str = str(resource_attrs_str)
            attrs = eval(attrs_str)  # Safe here since it's our own data
            return {
                "deployment": attrs.get("k8s.deployment.name", ""),
                "pod": attrs.get("k8s.pod.name", ""),
                "namespace": attrs.get("k8s.namespace.name", ""),
                "node": attrs.get("k8s.node.name", ""),
                "service": attrs.get("service.name", ""),
            }
        except Exception:
            return {}

    # Extract k8s metadata for filtering
    # Support two log formats:
    # 1. Raw OTEL format: ResourceAttributes column with nested k8s metadata
    # 2. Processed format: separate k8s_pod_name, k8s_namespace, service_name columns
    if "ResourceAttributes" in df.columns:
        k8s_metadata = df["ResourceAttributes"].apply(extract_k8s_metadata)
        df["_deployment"] = k8s_metadata.apply(lambda x: x.get("deployment", ""))
        df["_pod"] = k8s_metadata.apply(lambda x: x.get("pod", ""))
        df["_namespace"] = k8s_metadata.apply(lambda x: x.get("namespace", ""))
    else:
        # Use pre-extracted columns if available (processed format)
        df["_deployment"] = df.get("k8s_deployment_name", df.get("deployment", pd.Series([""] * len(df))))
        df["_pod"] = df.get("k8s_pod_name", df.get("pod_name", pd.Series([""] * len(df))))
        df["_namespace"] = df.get("k8s_namespace", df.get("namespace", pd.Series([""] * len(df))))
        # Fill NaN values
        df["_deployment"] = df["_deployment"].fillna("")
        df["_pod"] = df["_pod"].fillna("")
        df["_namespace"] = df["_namespace"].fillna("")

    # Filter by k8_object - supports namespace/kind/name, kind/name, or name formats
    if k8_object:
        parsed_id = _parse_k8_object_identifier(k8_object)

        if parsed_id["format"] == "invalid":
            return [TextContent(type="text", text=parsed_id.get("warning", "Invalid identifier"))]

        kind = parsed_id.get("kind")
        name = parsed_id.get("name", "")
        # namespace from parsed_id can be used for additional filtering if needed

        name_variants = [name.lower()]
        for suffix in ["-service", "_service", "-svc", "_svc"]:
            if name.lower().endswith(suffix):
                name_variants.append(name.lower()[: -len(suffix)])

        if kind:
            kind_lower = kind.lower()
            if kind_lower in ["deployment", "deploy"]:
                mask = df["_deployment"].str.lower().isin(name_variants)
            elif kind_lower == "pod":
                mask = df["_pod"].str.lower().str.contains("|".join(name_variants), na=False, regex=True)
            elif kind_lower in ["service", "svc", "app"]:
                svc_mask = (
                    df["ServiceName"].str.lower().isin(name_variants)
                    if "ServiceName" in df.columns
                    else pd.Series([False] * len(df))
                )
                deploy_mask = df["_deployment"].str.lower().isin(name_variants)
                mask = svc_mask | deploy_mask
            else:
                svc_mask = (
                    df["ServiceName"].str.lower().isin(name_variants)
                    if "ServiceName" in df.columns
                    else pd.Series([False] * len(df))
                )
                deploy_mask = df["_deployment"].str.lower().isin(name_variants)
                mask = svc_mask | deploy_mask
        else:
            # Name-only format - search across all k8s metadata fields
            svc_mask = (
                df["ServiceName"].str.lower().isin(name_variants)
                if "ServiceName" in df.columns
                else pd.Series([False] * len(df))
            )
            deploy_mask = df["_deployment"].str.lower().isin(name_variants)
            pod_mask = df["_pod"].str.lower().str.contains("|".join(name_variants), na=False, regex=True)
            mask = svc_mask | deploy_mask | pod_mask

        df = df[mask]

    # Filter by service_name
    if service_name and "ServiceName" in df.columns:
        df = df[df["ServiceName"].str.lower() == service_name.lower()]

    # Filter by severity
    if severity_filter and "SeverityText" in df.columns:
        severities = [s.strip().upper() for s in severity_filter.split(",")]
        df = df[df["SeverityText"].str.upper().isin(severities)]

    # Filter by body contains
    if body_contains and "Body" in df.columns:
        df = df[df["Body"].str.contains(body_contains, case=False, na=False)]

    # Filter by time window
    time_col = "Timestamp" if "Timestamp" in df.columns else "TimestampTime"
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        if start_time:
            df = df[df[time_col] >= _to_utc_timestamp(start_time)]
        if end_time:
            df = df[df[time_col] <= _to_utc_timestamp(end_time)]

    total_rows = len(df)

    if total_rows == 0:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "total_count": 0,
                        "filters_applied": {
                            "k8_object": k8_object,
                            "service_name": service_name,
                            "severity_filter": severity_filter,
                            "body_contains": body_contains,
                            "start_time": start_time_str,
                            "end_time": end_time_str,
                        },
                        "patterns" if pattern_analysis else "data": [],
                    },
                    indent=2,
                ),
            )
        ]

    # =========================================================================
    # PATTERN ANALYSIS MODE (using drain3)
    # =========================================================================
    if pattern_analysis:
        if TemplateMiner is None:
            return [
                TextContent(
                    type="text", text="Error: drain3 is required for pattern analysis. Install with: pip install drain3"
                )
            ]

        # Configure drain3 with similarity threshold
        # sim_th controls how similar logs must be to group together (default 0.4)
        # Lower threshold = more distinct patterns, higher = more grouping
        config = TemplateMinerConfig()
        config.drain_sim_th = similarity_threshold
        config.drain_depth = 4
        config.drain_max_children = 100
        config.drain_max_clusters = max_patterns * 2  # Allow some buffer

        # Add common masking patterns for cleaner templates using MaskingInstruction
        if MaskingInstruction is not None:
            config.masking_instructions = [
                # UUIDs (e.g., 3668f213-3a05-42a5-add7-927432543d35)
                MaskingInstruction(
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>"
                ),
                # IP addresses (simple pattern)
                MaskingInstruction(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>"),
                # Hex numbers
                MaskingInstruction(r"0x[0-9a-fA-F]+", "<HEX>"),
            ]

        template_miner = TemplateMiner(config=config)

        # Build index mapping: cluster_id -> list of (df_index, log_body)
        cluster_to_logs: Dict[int, List[tuple]] = {}
        log_bodies = df["Body"].fillna("").astype(str).tolist()
        df_indices = df.index.tolist()

        # Process each log message
        for df_idx, body in zip(df_indices, log_bodies):
            if not body.strip():
                continue
            result = template_miner.add_log_message(body)
            cluster_id = result.get("cluster_id")
            if cluster_id is not None:
                if cluster_id not in cluster_to_logs:
                    cluster_to_logs[cluster_id] = []
                cluster_to_logs[cluster_id].append((df_idx, body))

        # Build pattern results from clusters
        patterns = []
        for cluster in template_miner.drain.clusters:
            cluster_id = cluster.cluster_id
            pattern_template = cluster.get_template()

            # Get logs belonging to this cluster
            cluster_logs = cluster_to_logs.get(cluster_id, [])
            if not cluster_logs:
                continue

            matching_indices = [log[0] for log in cluster_logs]
            count = len(matching_indices)

            # Get example log (first one in cluster)
            example_idx = matching_indices[0]
            example_row = df.loc[example_idx]
            example_log = {
                "body": str(example_row.get("Body", ""))[:500],  # Truncate long bodies
                "timestamp": str(example_row.get(time_col, "")) if time_col in df.columns else None,
                "service": str(example_row.get("ServiceName", "")) if "ServiceName" in df.columns else None,
                "severity": str(example_row.get("SeverityText", "")) if "SeverityText" in df.columns else None,
            }

            # Compute severity breakdown
            severity_breakdown = {}
            if "SeverityText" in df.columns:
                matched_df = df.loc[matching_indices]
                severity_counts = matched_df["SeverityText"].value_counts().to_dict()
                severity_breakdown = {str(k): int(v) for k, v in severity_counts.items()}

            # Compute time range
            time_range = {}
            if time_col in df.columns:
                matched_df = df.loc[matching_indices]
                valid_times = matched_df[time_col].dropna()
                if len(valid_times) > 0:
                    time_range = {"first": str(valid_times.min()), "last": str(valid_times.max())}

            # Compute service breakdown
            service_breakdown = {}
            if "ServiceName" in df.columns:
                matched_df = df.loc[matching_indices]
                svc_counts = matched_df["ServiceName"].value_counts().to_dict()
                service_breakdown = {str(k): int(v) for k, v in svc_counts.items()}

            patterns.append(
                {
                    "pattern": pattern_template,
                    "count": count,
                    "percentage": round(100 * count / total_rows, 2),
                    "severity_breakdown": severity_breakdown,
                    "service_breakdown": service_breakdown,
                    "time_range": time_range,
                    "example": example_log,
                }
            )

        # Sort by count (most frequent first) and limit
        patterns.sort(key=lambda x: x["count"], reverse=True)
        patterns = patterns[:max_patterns]

        result = {
            "total_logs": total_rows,
            "pattern_count": len(patterns),
            "similarity_threshold": similarity_threshold,
            "filters_applied": {
                "k8_object": k8_object,
                "service_name": service_name,
                "severity_filter": severity_filter,
                "body_contains": body_contains,
                "start_time": start_time_str,
                "end_time": end_time_str,
            },
            "patterns": patterns,
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # =========================================================================
    # RAW LOG MODE (original pagination behavior)
    # =========================================================================
    # Sort by timestamp (most recent first)
    if time_col in df.columns:
        df = df.sort_values(time_col, ascending=False)

    # Apply pagination
    if offset > 0:
        df = df.iloc[offset:]
    if limit:
        df = df.head(limit)

    # Select output columns
    output_cols = []
    for col in [
        "Timestamp",
        "ServiceName",
        "SeverityText",
        "Body",
        "TraceId",
        "SpanId",
        "_deployment",
        "_pod",
        "_namespace",
    ]:
        if col in df.columns:
            output_cols.append(col)

    if output_cols:
        df_output = df[output_cols].copy()
    else:
        df_output = df.copy()

    # Convert timestamps to string for JSON
    for col in df_output.columns:
        if pd.api.types.is_datetime64_any_dtype(df_output[col]):
            df_output[col] = df_output[col].astype(str)

    # Rename internal columns
    col_rename = {"_deployment": "deployment", "_pod": "pod", "_namespace": "namespace"}
    df_output = df_output.rename(columns={k: v for k, v in col_rename.items() if k in df_output.columns})

    result = {
        "total_count": total_rows,
        "offset": offset,
        "limit": limit if limit else "all",
        "returned_count": len(df_output),
        "filters_applied": {
            "k8_object": k8_object,
            "service_name": service_name,
            "severity_filter": severity_filter,
            "body_contains": body_contains,
            "start_time": start_time_str,
            "end_time": end_time_str,
        },
        "data": json.loads(df_output.to_json(orient="records")),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]
