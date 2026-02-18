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

from ..shared import (
    _df_to_json_records,
    _extract_deployment_from_pod,
    _extract_object_info_from_filename,
    _filter_labels,
    _parse_k8_object_identifier,
    _parse_tags_to_dict,
    _parse_time,
    _to_utc_timestamp,
)


def _sanitize_metric_name(name: str) -> str:
    """Sanitize metric name to be valid Python/Pandas identifier.

    Replaces special characters with underscores so metric names can be used
    in eval expressions.

    e.g., cluster:namespace:pod_memory:active:kube_pod_container_resource_limits
          -> cluster_namespace_pod_memory_active_kube_pod_container_resource_limits
    """
    import re

    # Replace colons, dots, dashes, and other special chars with underscores
    sanitized = re.sub(r"[:\-\./\s]", "_", name)
    # Remove consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip("_")
    return sanitized


def _sanitize_eval_query(eval_query: str, name_mapping: dict[str, str]) -> str:
    """Transform eval query to use sanitized metric names.

    If the user wrote an eval using original metric names (with colons),
    automatically transform it to use sanitized names.
    """
    result = eval_query
    # Sort by length descending to replace longer names first (avoid partial matches)
    for original, sanitized in sorted(name_mapping.items(), key=lambda x: -len(x[0])):
        if original != sanitized:
            result = result.replace(original, sanitized)
    return result


def _prom_histogram_quantile(q: float, buckets: list[tuple[float, float]]) -> float | None:
    """Approximate Prometheus-style histogram_quantile for cumulative buckets.

    buckets: list of (le, cumulative_count), sorted by le.
    """
    if not buckets:
        return None

    # Ensure sorted and clean.
    buckets = [(le, cnt) for le, cnt in buckets if le is not None and cnt is not None]
    buckets.sort(key=lambda x: x[0])
    if not buckets:
        return None

    total = buckets[-1][1]
    try:
        total_f = float(total)
    except Exception:
        return None

    if total_f <= 0:
        return None

    rank = q * total_f
    prev_le = 0.0
    prev_cnt = 0.0

    for le, cnt in buckets:
        try:
            le_f = float(le)
            cnt_f = float(cnt)
        except Exception:
            continue

        if cnt_f >= rank:
            # If this is the +Inf bucket, return the previous boundary.
            if le_f == float("inf"):
                return prev_le

            bucket_cnt = cnt_f - prev_cnt
            if bucket_cnt <= 0:
                return le_f

            return prev_le + (le_f - prev_le) * ((rank - prev_cnt) / bucket_cnt)

        prev_le = le_f
        prev_cnt = cnt_f

    # Should not happen if last bucket is +Inf, but be defensive.
    return buckets[-1][0]


async def _metric_analysis(args: dict[str, Any]) -> list[TextContent]:
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    base_dir = args.get("base_dir", "")
    k8_object_name = args.get("k8_object_name")  # Now optional
    object_pattern = args.get("object_pattern", "*")  # Default: all objects
    metric_names = args.get("metric_names", [])
    eval_query = args.get("eval")
    filters = args.get("filters", {})
    group_by = args.get("group_by")
    agg_func = args.get("agg", "mean")
    verbosity = args.get("verbosity", "compact")  # "compact" | "raw"
    limit = int(args.get("limit", 200) or 0)  # 0 => no limit
    sort_by = args.get("sort_by")  # optional column name to sort descending
    include_tags = bool(args.get("include_tags", False))
    include_buckets = bool(args.get("include_buckets", False))
    labels_keep = args.get("labels_keep") or [
        # High-signal OTEL spanmetrics labels
        "span_name",
        "span_kind",
        "status_code",
        # Histogram bucket label (only meaningful if include_buckets=True)
        "le",
    ]
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    # Normalize start/end bounds to naive UTC datetimes for consistent comparison
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
        return [TextContent(type="text", text=f"Metrics directory not found: {base_dir}")]

    # Determine which files to load
    if k8_object_name:
        # Specific object requested - supports namespace/kind/name, kind/name, or name formats
        parsed_id = _parse_k8_object_identifier(k8_object_name)

        if parsed_id["format"] == "invalid":
            return [TextContent(type="text", text=parsed_id.get("warning", "Invalid identifier"))]

        kind = parsed_id.get("kind")
        name = parsed_id.get("name", "")

        if not kind:
            # Name-only format - try to infer from file patterns
            # Search all files matching *_{name}*.tsv
            files = list(base_path.glob(f"*_{name}*.tsv"))
            if not files:
                # Try without underscore
                files = list(base_path.glob(f"*{name}*.tsv"))
        else:
            # Try multiple name patterns to handle naming variations
            # e.g., "product-catalog-service" -> try "product-catalog-service", "product-catalog"
            name_variants = [name]
            for suffix in ["-service", "_service", "-svc", "_svc"]:
                if name.endswith(suffix):
                    name_variants.append(name[: -len(suffix)])

            files = []
            for variant in name_variants:
                prefix = f"{kind.lower()}_{variant}"
                files = list(base_path.glob(f"{prefix}*.tsv"))
                if files:
                    break
    else:
        # Batch mode: use object_pattern
        # Convert "pod/*" to "pod_*.tsv", "pod/frontend*" to "pod_frontend*.tsv"
        if "/" in object_pattern:
            kind, name_pattern = object_pattern.split("/", 1)
            glob_pattern = f"{kind.lower()}_{name_pattern}.tsv"
        else:
            glob_pattern = f"{object_pattern}.tsv" if object_pattern != "*" else "*.tsv"

        files = list(base_path.glob(glob_pattern))

    if not files:
        return [TextContent(type="text", text=f"No metric files found matching pattern")]

    all_data = []

    for file_path in files:
        try:
            df = pd.read_csv(file_path, sep="\t")

            # Extract object info from filename and add as columns
            obj_info = _extract_object_info_from_filename(file_path.name)
            df["_source_file"] = file_path.name
            df["_object_kind"] = obj_info["kind"]
            df["_object_name"] = obj_info["name"]

            # Extract deployment from pod name
            if obj_info["kind"] == "pod":
                df["deployment"] = _extract_deployment_from_pod(obj_info["name"])
            else:
                df["deployment"] = obj_info["name"]

            # Filter by metric names if provided
            if metric_names:
                if "metric_name" in df.columns:
                    df = df[df["metric_name"].isin(metric_names)]

            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

            # Time filter
            if start_time:
                df = df[df["timestamp"] >= _to_utc_timestamp(start_time)]
            if end_time:
                df = df[df["timestamp"] <= _to_utc_timestamp(end_time)]

            # Custom filters
            if filters:
                for col, val in filters.items():
                    if col in df.columns:
                        df = df[df[col] == val]

            if not df.empty:
                all_data.append(df)

        except Exception:
            continue

    if not all_data:
        return [TextContent(type="text", text="[]")]

    combined_df = pd.concat(all_data, ignore_index=True)

    compact_mode = verbosity != "raw"

    # =============================================================================
    # LLM-friendly output shaping (requested changes 1, 2, 4, 6)
    #
    # 1) Default away from raw rows: compact mode is default (verbosity="compact").
    # 2) Replace verbose `tags` with a small allowlisted `labels` dict.
    # 4) Dedupe duplicate rows.
    # 6) Hide histogram bucket metrics unless explicitly requested.
    # =============================================================================
    if compact_mode:
        # 6) Histogram buckets explode output and are hard for LLMs.
        # Default behavior:
        # - If user did NOT request bucket metrics: drop bucket rows entirely.
        # - If user DID request bucket metrics: compute p50/p90/p95/p99 from buckets (instead of returning raw buckets),
        #   unless include_buckets=True.
        requested_bucket_metrics = any(str(m).endswith("_bucket") for m in (metric_names or []))
        compute_bucket_quantiles = requested_bucket_metrics and not include_buckets
        if "metric_name" in combined_df.columns and not requested_bucket_metrics and not include_buckets:
            combined_df = combined_df[~combined_df["metric_name"].astype(str).str.endswith("_bucket")]

        # 2) Parse tags and keep only high-signal labels.
        if "tags" in combined_df.columns:
            parsed = combined_df["tags"].apply(_parse_tags_to_dict)
            combined_df["labels"] = parsed.apply(lambda d: _filter_labels(d, labels_keep))
            # For dedupe, use a stable, hashable signature (dicts are unhashable).
            combined_df["_labels_sig"] = combined_df["labels"].apply(
                lambda d: json.dumps(d, sort_keys=True, separators=(",", ":"))
            )
            # For bucket quantiles, group on labels WITHOUT `le`.
            combined_df["_labels_no_le_sig"] = combined_df["labels"].apply(
                lambda d: json.dumps({k: v for k, v in d.items() if k != "le"}, sort_keys=True, separators=(",", ":"))
            )
            if not include_tags:
                combined_df = combined_df.drop(columns=["tags"], errors="ignore")

        # 4) Dedupe after normalization.
        dedupe_cols = [
            c
            for c in [
                "timestamp",
                "metric_name",
                "metric_type",
                "namespace",
                "service_name",
                "status_code",
                "bucket_le",
                "value",
                "_labels_sig",
            ]
            if c in combined_df.columns
        ]
        if dedupe_cols:
            combined_df = combined_df.drop_duplicates(subset=dedupe_cols, keep="last")
        else:
            combined_df = combined_df.drop_duplicates(keep="last")

        # If bucket metrics were requested, compute quantiles and return compact rows (no raw buckets).
        if compute_bucket_quantiles and "metric_name" in combined_df.columns:
            bucket_df = combined_df[combined_df["metric_name"].astype(str).str.endswith("_bucket")]
            if not bucket_df.empty:
                # Convert bucket boundary to numeric, handling +Inf.
                if "bucket_le" in bucket_df.columns:
                    le_series = bucket_df["bucket_le"].astype(str)
                elif "labels" in bucket_df.columns:
                    le_series = bucket_df["labels"].apply(lambda d: d.get("le")).astype(str)
                else:
                    le_series = None

                if le_series is not None:
                    bucket_df = bucket_df.copy()
                    bucket_df["_le"] = pd.to_numeric(le_series.replace({"+Inf": "inf", "inf": "inf"}), errors="coerce")
                else:
                    bucket_df = bucket_df.copy()
                    bucket_df["_le"] = np.nan

                # Define grouping keys (exclude timestamp/le/value and internal columns).
                group_cols = [
                    c
                    for c in bucket_df.columns
                    if c not in ("timestamp", "bucket_le", "_le", "value", "labels", "_labels_sig")
                    and not c.startswith("_")
                ]
                # Ensure labels grouping uses the no-le signature (avoid per-bucket duplication).
                if "_labels_no_le_sig" in bucket_df.columns and "_labels_no_le_sig" not in group_cols:
                    group_cols.append("_labels_no_le_sig")

                # Find the latest timestamp per group and compute quantiles at that timestamp.
                latest_ts = bucket_df.groupby(group_cols, dropna=False)["timestamp"].max().reset_index()
                bucket_latest = bucket_df.merge(latest_ts, on=group_cols + ["timestamp"], how="inner")

                out_rows: list[dict[str, Any]] = []
                for _, g in bucket_latest.groupby(group_cols, dropna=False):
                    # Build bucket list (le, cumulative_count).
                    buckets = list(
                        zip(g["_le"].tolist(), pd.to_numeric(g["value"], errors="coerce").fillna(0.0).tolist())
                    )
                    # Sort and compute.
                    p50 = _prom_histogram_quantile(0.50, buckets)
                    p90 = _prom_histogram_quantile(0.90, buckets)
                    p95 = _prom_histogram_quantile(0.95, buckets)
                    p99 = _prom_histogram_quantile(0.99, buckets)

                    # Use the +Inf bucket count as sample_count if present.
                    try:
                        sample_count = float(max(cnt for le, cnt in buckets if le == float("inf")))
                    except Exception:
                        sample_count = float(max(cnt for _, cnt in buckets)) if buckets else 0.0

                    base = {}
                    # Pull representative dimension columns from the first row.
                    first = g.iloc[0]
                    for c in group_cols:
                        if c == "_labels_no_le_sig":
                            continue
                        base[c] = first.get(c)

                    # Attach labels (no-le) back as dict.
                    if "_labels_no_le_sig" in g.columns:
                        try:
                            base["labels"] = json.loads(first.get("_labels_no_le_sig") or "{}")
                        except Exception:
                            base["labels"] = {}

                    base["timestamp"] = str(first.get("timestamp"))
                    base["sample_count"] = sample_count
                    base["duration_ms"] = {"p50": p50, "p90": p90, "p95": p95, "p99": p99}
                    out_rows.append(base)

                out_df = pd.DataFrame(out_rows)
                if sort_by and sort_by in out_df.columns:
                    out_df = out_df.sort_values(sort_by, ascending=False)
                if limit and len(out_df) > limit:
                    out_df = out_df.head(limit)

                return [TextContent(type="text", text=_df_to_json_records(out_df, compact=True))]

    # If eval is requested, we need to pivot so metrics are columns
    if eval_query:
        if "metric_name" not in combined_df.columns or "value" not in combined_df.columns:
            return [TextContent(type="text", text="Error: Cannot perform eval - missing metric_name or value columns")]

        # Build mapping of original metric names to sanitized names
        unique_metrics = combined_df["metric_name"].unique()
        name_mapping = {m: _sanitize_metric_name(m) for m in unique_metrics}
        sanitized_eval = _sanitize_eval_query(eval_query, name_mapping)

        # Detect mode based on group_by: per-object or cluster-wide
        per_object_mode = group_by in ("deployment", "pod_name", "_object_name")

        try:
            if per_object_mode:
                # PER-OBJECT MODE: Compute derived metric at each timestamp FIRST, then aggregate
                # This ensures ratios like throttle_pct are computed correctly before aggregation
                pivot_dfs = []

                for obj_name, obj_df in combined_df.groupby("_object_name"):
                    # Pivot with timestamp index - keep all data points
                    pivot_df = obj_df.pivot_table(
                        index="timestamp",
                        columns="metric_name",
                        values="value",
                        aggfunc="mean",  # For duplicate timestamps, use mean
                    )

                    # Forward-fill to handle misaligned timestamps
                    pivot_df = pivot_df.ffill().bfill()
                    pivot_df.columns = [_sanitize_metric_name(c) for c in pivot_df.columns]

                    # Compute derived metric (e.g., throttle_pct) at each timestamp
                    pivot_df.eval(sanitized_eval, inplace=True)

                    # Add object metadata
                    pivot_df = pivot_df.reset_index()
                    pivot_df["_object_name"] = obj_name
                    pivot_df["deployment"] = (
                        obj_df["deployment"].iloc[0] if "deployment" in obj_df.columns else obj_name
                    )
                    pivot_df["pod_name"] = obj_name
                    pivot_dfs.append(pivot_df)

                combined_df = pd.concat(pivot_dfs, ignore_index=True)
            else:
                # CLUSTER-WIDE MODE: Sum across all objects at each timestamp, then compute derived metric
                pivot_df = combined_df.pivot_table(
                    index="timestamp", columns="metric_name", values="value", aggfunc="sum"
                )

                # Forward-fill to handle misaligned timestamps
                pivot_df = pivot_df.ffill().bfill()
                pivot_df.columns = [_sanitize_metric_name(c) for c in pivot_df.columns]

                # Compute derived metric
                pivot_df.eval(sanitized_eval, inplace=True)

                if "=" not in sanitized_eval:
                    result = pivot_df.eval(sanitized_eval)
                    if isinstance(result, pd.Series):
                        pivot_df["result"] = result

                combined_df = pivot_df.reset_index()

        except Exception as e:
            sanitized_names = list(name_mapping.values())
            return [
                TextContent(
                    type="text", text=f"Error in eval: {e}\n" f"Available columns (sanitized): {sanitized_names}"
                )
            ]

    # 1) In compact mode, default to a summary rather than returning raw rows.
    # Users can still request time series via group_by="timestamp", or full raw output via verbosity="raw".
    if compact_mode and not group_by and not eval_query and agg_func == "mean":
        if "value" in combined_df.columns:
            # Treat all non-internal, non-value columns as dimensions; collapse timestamps.
            dim_cols = [c for c in combined_df.columns if c not in ("timestamp", "value") and not c.startswith("_")]

            if dim_cols:
                used_label_sig = False
                # `labels` is a dict (unhashable) - use `_labels_sig` for grouping if available.
                if "labels" in dim_cols:
                    if "_labels_sig" in combined_df.columns:
                        dim_cols = ["_labels_sig" if c == "labels" else c for c in dim_cols]
                        used_label_sig = True
                    else:
                        # Fall back to a stable string representation for grouping.
                        combined_df["_labels_sig"] = combined_df["labels"].apply(
                            lambda d: json.dumps(d, sort_keys=True, separators=(",", ":"))
                        )
                        dim_cols = ["_labels_sig" if c == "labels" else c for c in dim_cols]
                        used_label_sig = True

                stats = (
                    combined_df.groupby(dim_cols, dropna=False)["value"]
                    .agg(count="count", mean="mean", min="min", max="max")
                    .reset_index()
                )

                if "timestamp" in combined_df.columns:
                    # Attach last observed value + timestamp per dimension.
                    idx = combined_df.groupby(dim_cols, dropna=False)["timestamp"].idxmax()
                    last = combined_df.loc[idx, dim_cols + ["timestamp", "value"]].rename(
                        columns={"timestamp": "last_timestamp", "value": "last_value"}
                    )
                    out = stats.merge(last, on=dim_cols, how="left")
                else:
                    out = stats

                if used_label_sig and "_labels_sig" in out.columns:
                    out["labels"] = out["_labels_sig"].apply(json.loads)
                    out = out.drop(columns=["_labels_sig"], errors="ignore")

                # Sort/limit for compact mode.
                if sort_by and sort_by in out.columns:
                    out = out.sort_values(sort_by, ascending=False)
                elif "max" in out.columns:
                    out = out.sort_values("max", ascending=False)

                if limit and len(out) > limit:
                    out = out.head(limit)

                return [TextContent(type="text", text=_df_to_json_records(out, compact=True))]

            # No dimension columns (edge case) -> just a global summary.
            summary = combined_df["value"].agg(["count", "mean", "min", "max"]).to_frame().T
            return [TextContent(type="text", text=_df_to_json_records(summary, compact=True))]

    # Group By and Aggregation
    if group_by:
        # Handle special 'deployment' extraction from pod names
        if group_by == "deployment" and "deployment" not in combined_df.columns:
            if "pod_name" in combined_df.columns:
                combined_df["deployment"] = combined_df["pod_name"].apply(_extract_deployment_from_pod)
            elif "_object_name" in combined_df.columns:
                combined_df["deployment"] = combined_df["_object_name"].apply(_extract_deployment_from_pod)

        if group_by in combined_df.columns:
            numeric_cols = combined_df.select_dtypes(include=[np.number]).columns.tolist()
            numeric_cols = [c for c in numeric_cols if not c.startswith("_")]

            if numeric_cols:
                grouped = combined_df.groupby(group_by)[numeric_cols].agg(agg_func).reset_index()
                # Sort by eval result column if present
                if len(numeric_cols) > 0:
                    eval_col = None
                    if eval_query and "=" in eval_query:
                        eval_col = eval_query.split("=")[0].strip()
                    sort_col = eval_col if eval_col and eval_col in grouped.columns else numeric_cols[-1]
                    grouped = grouped.sort_values(sort_col, ascending=False)

                if compact_mode and sort_by and sort_by in grouped.columns:
                    grouped = grouped.sort_values(sort_by, ascending=False)
                if compact_mode and limit and len(grouped) > limit:
                    grouped = grouped.head(limit)

                return [TextContent(type="text", text=_df_to_json_records(grouped, compact=compact_mode))]
            else:
                return [TextContent(type="text", text=f"Error: No numeric columns found for aggregation")]
        else:
            return [
                TextContent(
                    type="text", text=f"Error: Column '{group_by}' not found. Available: {list(combined_df.columns)}"
                )
            ]

    # If no group_by but agg is specified, aggregate all rows
    if agg_func and agg_func != "mean":  # 'mean' is default, so explicit agg requested
        numeric_cols = combined_df.select_dtypes(include=[np.number]).columns.tolist()
        numeric_cols = [c for c in numeric_cols if not c.startswith("_")]
        if numeric_cols:
            result = combined_df[numeric_cols].agg(agg_func).to_frame().T
            return [TextContent(type="text", text=_df_to_json_records(result, compact=compact_mode))]

    # Return data
    # If we pivoted, we have wide format. If not, long format.
    if "timestamp" in combined_df.columns:
        combined_df = combined_df.sort_values("timestamp")
        combined_df["timestamp"] = combined_df["timestamp"].astype(str)

    # Drop internal columns for cleaner output
    output_df = combined_df.drop(columns=[c for c in combined_df.columns if c.startswith("_")], errors="ignore")

    if compact_mode and sort_by and sort_by in output_df.columns:
        output_df = output_df.sort_values(sort_by, ascending=False)
    if compact_mode and limit and len(output_df) > limit:
        output_df = output_df.head(limit)

    return [TextContent(type="text", text=_df_to_json_records(output_df, compact=compact_mode))]
