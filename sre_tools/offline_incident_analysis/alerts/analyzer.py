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

from ..shared import _extract_alert_snapshot_timestamp, _parse_time


def _resolve_alert_column(col: str, available_cols: list) -> str:
    """Resolve column shortcuts for alerts.

    Maps user-friendly names to actual flattened column names:
    - alertname → labels.alertname
    - severity → labels.severity
    - service_name → labels.service_name
    - namespace → labels.namespace
    """
    shortcuts = {
        "alertname": "labels.alertname",
        "severity": "labels.severity",
        "service_name": "labels.service_name",
        "service": "labels.service_name",
        "namespace": "labels.namespace",
    }

    # Check if it's a shortcut
    if col in shortcuts:
        resolved = shortcuts[col]
        if resolved in available_cols:
            return resolved

    # Return as-is if it exists
    if col in available_cols:
        return col

    # Try with labels. prefix
    if f"labels.{col}" in available_cols:
        return f"labels.{col}"

    return col  # Return original, will fail later if invalid


async def _alert_analysis(args: dict[str, Any]) -> list[TextContent]:
    """Analyze alerts with SQL-like filter → group_by → agg flow."""
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    base_dir = args.get("base_dir", "")
    time_basis = args.get("time_basis", "snapshot")
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

    # Normalize start/end bounds to naive UTC datetimes for consistent comparison.
    # (Snapshot timestamps are parsed as UTC then made tz-naive.)
    start_bound = None
    end_bound = None
    if start_time:
        st = pd.Timestamp(start_time)
        if st.tzinfo is not None:
            st = st.tz_convert("UTC").tz_localize(None)
        start_bound = st.to_pydatetime()
    if end_time:
        et = pd.Timestamp(end_time)
        if et.tzinfo is not None:
            et = et.tz_convert("UTC").tz_localize(None)
        end_bound = et.to_pydatetime()

    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Alerts directory not found: {base_dir}")]

    # Auto-detect alerts/ subdirectory if base_path doesn't have JSON files directly
    alerts_subdir = base_path / "alerts"
    if alerts_subdir.is_dir() and not list(base_path.glob("*.json")):
        base_path = alerts_subdir

    # Load all alerts from JSON files
    all_alerts = []

    for json_file in sorted(base_path.glob("*.json")):
        try:
            data = read_json_file(json_file)

            file_ts = _extract_alert_snapshot_timestamp(json_file, data)

            # Handle nested structure: data.alerts or just alerts array
            if isinstance(data, dict):
                if "data" in data and "alerts" in data["data"]:
                    alerts_list = data["data"]["alerts"]
                elif "alerts" in data:
                    alerts_list = data["alerts"]
                else:
                    alerts_list = [data]
            else:
                alerts_list = data if isinstance(data, list) else [data]

            # Add file timestamp to each alert for duration calculation (only if we have a valid timestamp)
            if file_ts:
                for alert in alerts_list:
                    alert["_file_timestamp"] = file_ts

            all_alerts.extend(alerts_list)
        except Exception:
            continue

    if not all_alerts:
        return [TextContent(type="text", text="[]")]

    # Normalize JSON to DataFrame (flattens nested labels/annotations)
    df = pd.json_normalize(all_alerts)

    # Compute duration_active (how long alert has been firing at the snapshot time)
    time_col = "activeAt" if "activeAt" in df.columns else "startsAt"
    if time_col in df.columns and "_file_timestamp" in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        df["_file_timestamp"] = pd.to_datetime(df["_file_timestamp"], errors="coerce", utc=True)

        # Remove timezone info for consistent comparison
        if df[time_col].dt.tz is not None:
            df[time_col] = df[time_col].dt.tz_localize(None)
        if df["_file_timestamp"].dt.tz is not None:
            df["_file_timestamp"] = df["_file_timestamp"].dt.tz_localize(None)

        # Duration in minutes (snapshot_time - activeAt)
        df["duration_active_min"] = (df["_file_timestamp"] - df[time_col]).dt.total_seconds() / 60

        # Set negative durations (invalid) to NaN
        df.loc[df["duration_active_min"] < 0, "duration_active_min"] = pd.NA
        df["duration_active_min"] = df["duration_active_min"].round(1)

        # Human-readable duration
        def format_duration(minutes):
            if pd.isna(minutes):
                return "unknown"
            if minutes < 1:
                return "<1m"
            elif minutes < 60:
                return f"{int(minutes)}m"
            elif minutes < 1440:
                return f"{int(minutes // 60)}h {int(minutes % 60)}m"
            else:
                return f"{int(minutes // 1440)}d {int((minutes % 1440) // 60)}h"

        df["duration_active"] = df["duration_active_min"].apply(format_duration)

    # Expose snapshot timestamp as a stable output column (keep internal _file_timestamp for computations)
    if "_file_timestamp" in df.columns and "snapshot_timestamp" not in df.columns:
        df["snapshot_timestamp"] = df["_file_timestamp"]

    # Convert value to numeric
    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Apply filters (with shortcut resolution)
    if filters:
        for col, val in filters.items():
            resolved_col = _resolve_alert_column(col, list(df.columns))
            if resolved_col in df.columns:
                df = df[df[resolved_col] == val]
            else:
                return [
                    TextContent(
                        type="text", text=f"Error: Filter column '{col}' not found. Available: {list(df.columns)}"
                    )
                ]

    # Filter by time window (defaults to observation/snapshot time)
    basis_col = time_col
    if time_basis != "activeAt" and "_file_timestamp" in df.columns:
        basis_col = "_file_timestamp"

    if basis_col in df.columns:
        if start_time:
            start_ts = pd.Timestamp(start_time)
            if start_ts.tzinfo is not None:
                start_ts = start_ts.tz_convert("UTC").tz_localize(None)
            df = df[df[basis_col] >= start_ts]
        if end_time:
            end_ts = pd.Timestamp(end_time)
            if end_ts.tzinfo is not None:
                end_ts = end_ts.tz_convert("UTC").tz_localize(None)
            df = df[df[basis_col] <= end_ts]

    # Group By with multiple aggregation types
    if group_by:
        # Normalize group_by to list and resolve shortcuts
        group_cols_input = [group_by] if isinstance(group_by, str) else list(group_by)
        group_cols = [_resolve_alert_column(c, list(df.columns)) for c in group_cols_input]

        # Check all group columns exist
        for col in group_cols:
            if col not in df.columns:
                return [
                    TextContent(
                        type="text", text=f"Error: Group column '{col}' not found. Available: {list(df.columns)}"
                    )
                ]

        # Perform aggregation
        if agg_type == "count":
            grouped = df.groupby(group_cols).size().reset_index(name="count")
            sort_col = sort_by if sort_by and sort_by in grouped.columns else "count"
            grouped = grouped.sort_values(sort_col, ascending=False)

        elif agg_type == "first":
            sort_time_col = basis_col if basis_col in df.columns else time_col
            if sort_time_col in df.columns:
                grouped = df.sort_values(sort_time_col).groupby(group_cols).first().reset_index()
            else:
                grouped = df.groupby(group_cols).first().reset_index()

        elif agg_type == "last":
            sort_time_col = basis_col if basis_col in df.columns else time_col
            if sort_time_col in df.columns:
                grouped = df.sort_values(sort_time_col).groupby(group_cols).last().reset_index()
            else:
                grouped = df.groupby(group_cols).last().reset_index()

        elif agg_type in ("sum", "mean", "max", "min"):
            # Numeric aggregations on value and duration columns
            numeric_cols = ["value", "duration_active_min"]
            numeric_cols = [c for c in numeric_cols if c in df.columns]

            if numeric_cols:
                grouped = df.groupby(group_cols)[numeric_cols].agg(agg_type).reset_index()
                if sort_by and sort_by in grouped.columns:
                    grouped = grouped.sort_values(sort_by, ascending=False)
                elif "value" in grouped.columns:
                    grouped = grouped.sort_values("value", ascending=False)
            else:
                return [TextContent(type="text", text=f"Error: No numeric columns for {agg_type} aggregation")]
        else:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Unknown aggregation '{agg_type}'. Use: count, first, last, sum, mean, max, min",
                )
            ]

        total_rows = len(grouped)

        # Apply offset and limit (pagination)
        if offset > 0:
            grouped = grouped.iloc[offset:]
        if limit:
            grouped = grouped.head(limit)

        # Clean up internal columns and convert timestamps
        grouped = grouped.drop(columns=[c for c in grouped.columns if c.startswith("_")], errors="ignore")
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
    if sort_by:
        resolved_sort = _resolve_alert_column(sort_by, list(df.columns))
        if resolved_sort in df.columns:
            ascending = not (sort_by in ["duration_active_min", "value", "count"])  # Desc for these
            df = df.sort_values(resolved_sort, ascending=ascending)
    else:
        sort_time_col = basis_col if basis_col in df.columns else time_col
        if sort_time_col in df.columns:
            df = df.sort_values(sort_time_col)

    total_rows = len(df)

    # Apply offset and limit (pagination)
    if offset > 0:
        df = df.iloc[offset:]
    if limit:
        df = df.head(limit)

    # Clean up and convert timestamps
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
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


# =============================================================================
# Alert Summary
# =============================================================================


async def _alert_summary(args: dict[str, Any]) -> list[TextContent]:
    """Provide a high-level summary of all alerts.

    For each unique alert type (alertname + entity + severity), calculates:
    - first_seen: earliest observation time in this dataset (snapshot time) while firing
    - last_seen: latest observation time in this dataset (snapshot time) while firing
    - duration_min: difference between last_seen and first_seen (observed incident window)
    """
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    base_dir = args.get("base_dir", "")
    time_basis = args.get("time_basis", "snapshot")
    state_filter = args.get("state_filter")
    min_duration_min = args.get("min_duration_min")
    limit = args.get("limit", 50)
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    # Normalize start/end bounds to naive UTC datetimes for consistent comparison.
    # (Snapshot timestamps are parsed as UTC then made tz-naive.)
    start_bound = None
    end_bound = None
    if start_time:
        st = pd.Timestamp(start_time)
        if st.tzinfo is not None:
            st = st.tz_convert("UTC").tz_localize(None)
        start_bound = st.to_pydatetime()
    if end_time:
        et = pd.Timestamp(end_time)
        if et.tzinfo is not None:
            et = et.tz_convert("UTC").tz_localize(None)
        end_bound = et.to_pydatetime()

    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Alerts directory not found: {base_dir}")]

    # Auto-detect alerts/ subdirectory
    alerts_subdir = base_path / "alerts"
    if alerts_subdir.is_dir() and not list(base_path.glob("*.json")):
        base_path = alerts_subdir

    # Load all alerts from JSON files
    all_alerts = []

    for json_file in sorted(base_path.glob("*.json")):
        try:
            data = read_json_file(json_file)

            snapshot_ts = _extract_alert_snapshot_timestamp(json_file, data)
            snapshot_dt = None
            if snapshot_ts:
                try:
                    snapshot_dt = pd.to_datetime(snapshot_ts, utc=True).tz_localize(None).to_pydatetime()
                except Exception:
                    snapshot_dt = None

            # If we're doing snapshot-based filtering, filter at the file level.
            if time_basis != "activeAt" and snapshot_dt and (start_bound or end_bound):
                start_ok = True
                end_ok = True
                if start_bound:
                    start_ok = snapshot_dt >= start_bound
                if end_bound:
                    end_ok = snapshot_dt <= end_bound
                if not (start_ok and end_ok):
                    continue

            # Handle nested structure
            if isinstance(data, dict):
                if "data" in data and "alerts" in data["data"]:
                    alerts_list = data["data"]["alerts"]
                elif "alerts" in data:
                    alerts_list = data["alerts"]
                else:
                    alerts_list = [data]
            else:
                alerts_list = data if isinstance(data, list) else [data]

            # Stamp each alert with the snapshot timestamp for observation-based summaries.
            if snapshot_ts:
                for alert in alerts_list:
                    if isinstance(alert, dict):
                        alert["_snapshot_timestamp"] = snapshot_ts

            all_alerts.extend(alerts_list)

        except Exception:
            pass

    if not all_alerts:
        return [TextContent(type="text", text="[]")]

    # Build summary by grouping alerts
    # Key: (alertname, entity, severity) -> {active_at_times, occurrences, states_seen, ...}
    alert_summaries: dict[tuple, dict] = {}

    for alert in all_alerts:
        labels = alert.get("labels", {})
        alertname = labels.get("alertname", alert.get("alertname", "Unknown"))

        # Determine entity (service, pod, deployment, etc.)
        entity = (
            labels.get("service_name")
            or labels.get("service")
            or labels.get("pod")
            or labels.get("deployment")
            or labels.get("instance")
            or labels.get("job")
            or labels.get("namespace", "cluster-wide")
        )

        severity = labels.get("severity", "unknown")
        namespace = labels.get("namespace", "unknown")
        state = alert.get("state", "unknown")

        # Parse activeAt timestamp (when alert first became active) - useful metadata.
        active_at = None
        if "activeAt" in alert:
            try:
                ts = pd.to_datetime(alert["activeAt"])
                active_at = ts.tz_localize(None) if ts.tzinfo is None else ts.tz_convert(None)
                active_at = active_at.to_pydatetime()
            except Exception:
                pass

        # Parse observation/snapshot time (when this alert was observed in the dump)
        snapshot_at = None
        if "_snapshot_timestamp" in alert:
            try:
                ts = pd.to_datetime(alert["_snapshot_timestamp"], utc=True)
                snapshot_at = ts.tz_localize(None).to_pydatetime()
            except Exception:
                snapshot_at = None

        key = (alertname, entity, severity)

        if key not in alert_summaries:
            alert_summaries[key] = {
                "alertname": alertname,
                "entity": entity,
                "severity": severity,
                "namespace": namespace,
                "times": set(),  # snapshot times by default (or activeAt if time_basis='activeAt')
                "occurrences": 0,
                "states_seen": set(),
                "latest_state": state,
                "latest_time": None,
            }

        summary = alert_summaries[key]
        summary["occurrences"] += 1
        summary["states_seen"].add(state)

        # Track latest state based on the chosen time basis when possible.
        time_for_latest = snapshot_at if time_basis != "activeAt" else active_at
        if time_for_latest is not None:
            if summary["latest_time"] is None or time_for_latest >= summary["latest_time"]:
                summary["latest_time"] = time_for_latest
                summary["latest_state"] = state
        else:
            # Fallback: keep updating to get the latest state in iteration order.
            summary["latest_state"] = state

        # Track time axis for alerts that are actively firing
        if state == "firing":
            t = active_at if time_basis == "activeAt" else snapshot_at
            if t is not None:
                if start_bound and t < start_bound:
                    pass
                elif end_bound and t > end_bound:
                    pass
                else:
                    summary["times"].add(t)

    # Convert to list with calculated durations
    results = []
    for key, summary in alert_summaries.items():
        active_times = sorted(summary["times"])

        if active_times:
            first_seen = active_times[0]
            last_seen = active_times[-1]
            # Duration = observed time span within this dataset/window
            duration_min = (last_seen - first_seen).total_seconds() / 60
            duration_min = round(duration_min, 1)
        else:
            first_seen = None
            last_seen = None
            duration_min = None

        # Determine the effective state (prefer 'firing' if seen)
        state = summary["latest_state"]
        if "firing" in summary["states_seen"]:
            state = "firing"

        results.append(
            {
                "alertname": summary["alertname"],
                "entity": summary["entity"],
                "namespace": summary["namespace"],
                "severity": summary["severity"],
                "state": state,
                "first_seen": str(first_seen) if first_seen else None,
                "last_seen": str(last_seen) if last_seen else None,
                "duration_min": duration_min,
                "occurrences": summary["occurrences"],
            }
        )

    # Apply filters
    if state_filter:
        results = [r for r in results if r["state"] == state_filter]

    # If a time window was provided, only keep alerts observed firing in that window.
    if start_bound or end_bound:
        results = [r for r in results if r["first_seen"] is not None]

    if min_duration_min is not None:
        results = [r for r in results if r["duration_min"] is not None and r["duration_min"] >= min_duration_min]

    # Sort by duration (longest first), then by occurrences
    results.sort(key=lambda x: (-(x["duration_min"] or 0), -x["occurrences"]))

    # Apply limit
    if limit:
        results = results[:limit]

    return [TextContent(type="text", text=json.dumps(results, indent=2))]


# =============================================================================
# K8s Spec Change Analysis
# =============================================================================

# Fields to ignore when computing spec diffs (these cause "churn" without meaningful changes)
_IGNORE_SPEC_FIELDS = {
    "resourceVersion",
    "managedFields",
    "generation",
    "uid",
    "selfLink",
    "creationTimestamp",
    "time",
    "lastTransitionTime",
    "lastUpdateTime",
    "lastProbeTime",
    "lastHeartbeatTime",
    "observedGeneration",
    "containerStatuses",
    "conditions",
    "podIP",
    "podIPs",
    "hostIP",
    "startTime",
    "status",  # Status is often ephemeral
}

# Annotations that are timestamp-related
_IGNORE_ANNOTATIONS = {
    "endpoints.kubernetes.io/last-change-trigger-time",
    "kubectl.kubernetes.io/last-applied-configuration",
    "deployment.kubernetes.io/revision",
}

_PRESERVE_TIMESTAMP_KEYS = {
    # Useful lifecycle evidence; do not drop just because it contains "timestamp".
    "deletiontimestamp",
}
