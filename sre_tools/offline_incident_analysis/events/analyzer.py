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


def _convert_otel_events_to_flat(df: "pd.DataFrame") -> "pd.DataFrame":
    """Convert OTEL-format events DataFrame to flat format.

    Detects if DataFrame is in OTEL format (has 'Body' column) and converts it.
    """
    if "Body" not in df.columns:
        return df

    # Parse Body JSON and flatten
    parsed_rows = []
    for idx, row in df.iterrows():
        parsed = _parse_otel_event_body(row.get("Body", ""))
        if parsed.get("object_name"):  # Only include rows with valid data
            # Keep original timestamp if available
            if "Timestamp" in row and row["Timestamp"]:
                parsed["log_timestamp"] = row["Timestamp"]
            parsed_rows.append(parsed)

    if not parsed_rows:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(
            columns=[
                "object_kind",
                "object_name",
                "namespace",
                "reason",
                "message",
                "event_time",
                "event_kind",
                "watch_type",
                "count",
                "source_component",
            ]
        )

    return pd.DataFrame(parsed_rows)


async def _event_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze Kubernetes events with SQL-like filter → group_by → agg flow.

    Supports both flat format (with columns like object_name, reason, etc.)
    and OTEL format (with Body column containing nested JSON).
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    events_file = args.get("events_file", "")
    filters = args.get("filters", {})
    group_by = args.get("group_by")
    agg_type = args.get("agg", "count")
    sort_by = args.get("sort_by")
    limit = args.get("limit")
    offset = args.get("offset", 0)
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")

    # limit=0 means no limit (fetch all)
    if limit == 0:
        limit = None

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    if not Path(events_file).exists():
        return [TextContent(type="text", text=f"Events file not found: {events_file}")]

    try:
        df = pd.read_csv(events_file, sep="\t")
    except Exception as e:
        return [TextContent(type="text", text=f"Error reading events file: {e}")]

    # Convert OTEL format to flat format if needed
    if "Body" in df.columns:
        df = _convert_otel_events_to_flat(df)
        if df.empty:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "total_count": 0,
                            "offset": 0,
                            "limit": limit if limit else "all",
                            "returned_count": 0,
                            "data": [],
                            "note": "Events file is in OTEL format but no valid K8s events found",
                        },
                        indent=2,
                    ),
                )
            ]

    # Add deployment column (extracted from pod/replicaset names in object_name)
    if "object_name" in df.columns and "object_kind" in df.columns:

        def extract_deployment(row):
            obj_kind = row.get("object_kind", "")
            obj_name = str(row.get("object_name", ""))
            if obj_kind == "Pod":
                # Pod: <deployment>-<rs-hash>-<pod-hash>
                return _extract_deployment_from_pod(obj_name)
            elif obj_kind == "ReplicaSet":
                # ReplicaSet: <deployment>-<rs-hash>
                parts = obj_name.rsplit("-", 1)
                if len(parts) >= 2 and len(parts[-1]) >= 5:  # hash is typically 9-10 chars
                    return parts[0]
            return obj_name if obj_name else "unknown"

        df["deployment"] = df.apply(extract_deployment, axis=1)

    # Apply filters
    if filters:
        for col, val in filters.items():
            if col in df.columns:
                df = df[df[col] == val]
            else:
                return [
                    TextContent(
                        type="text", text=f"Error: Filter column '{col}' not found. Available: {list(df.columns)}"
                    )
                ]

    # Filter by time
    time_col = "event_time" if "event_time" in df.columns else "timestamp"
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        if start_time:
            df = df[df[time_col] >= _to_utc_timestamp(start_time)]
        if end_time:
            df = df[df[time_col] <= _to_utc_timestamp(end_time)]

    # Group By with multiple aggregation types
    if group_by:
        # Normalize group_by to list
        group_cols = [group_by] if isinstance(group_by, str) else list(group_by)

        # Check all group columns exist
        for col in group_cols:
            if col not in df.columns:
                return [
                    TextContent(
                        type="text", text=f"Error: Group column '{col}' not found. Available: {list(df.columns)}"
                    )
                ]

        # Perform aggregation based on type
        if agg_type == "count":
            grouped = df.groupby(group_cols).size().reset_index(name="count")
            sort_col = sort_by if sort_by and sort_by in grouped.columns else "count"
            grouped = grouped.sort_values(sort_col, ascending=False)

        elif agg_type == "first":
            grouped = df.sort_values(time_col).groupby(group_cols).first().reset_index()

        elif agg_type == "last":
            grouped = df.sort_values(time_col).groupby(group_cols).last().reset_index()

        elif agg_type == "nunique":
            # Count unique values in each non-group column
            agg_dict = {col: "nunique" for col in df.columns if col not in group_cols}
            grouped = df.groupby(group_cols).agg(agg_dict).reset_index()
            # Rename columns to indicate they are counts
            grouped.columns = [f"{col}_unique" if col not in group_cols else col for col in grouped.columns]

        elif agg_type == "list":
            # List unique values (useful for seeing all reasons for a pod)
            agg_dict = {
                col: lambda x: list(x.unique())[:10] for col in ["reason", "message", "event_kind"] if col in df.columns
            }
            if agg_dict:
                grouped = df.groupby(group_cols).agg(agg_dict).reset_index()
            else:
                grouped = df.groupby(group_cols).size().reset_index(name="count")
        else:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Unknown aggregation type '{agg_type}'. Use: count, first, last, nunique, list",
                )
            ]

        total_rows = len(grouped)

        # Apply offset and limit (pagination)
        if offset > 0:
            grouped = grouped.iloc[offset:]
        if limit:
            grouped = grouped.head(limit)

        # Convert timestamps to string for JSON
        for col in grouped.columns:
            if pd.api.types.is_datetime64_any_dtype(grouped[col]):
                grouped[col] = grouped[col].astype(str)

        # Include pagination metadata
        result = {
            "total_count": total_rows,
            "offset": offset,
            "limit": limit if limit else "all",
            "returned_count": len(grouped),
            "data": json.loads(grouped.to_json(orient="records")),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # No group_by - return filtered data
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by)
    elif time_col in df.columns:
        df = df.sort_values(time_col)

    total_rows = len(df)

    # Apply offset and limit (pagination)
    if offset > 0:
        df = df.iloc[offset:]
    if limit:
        df = df.head(limit)

    # Convert timestamps to string for JSON
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)

    # Include pagination metadata
    result = {
        "total_count": total_rows,
        "offset": offset,
        "limit": limit if limit else "all",
        "returned_count": len(df),
        "data": json.loads(df.to_json(orient="records")),
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]
