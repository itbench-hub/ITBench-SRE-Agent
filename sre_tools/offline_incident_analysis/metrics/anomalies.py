"""
Anomaly detection for metrics.
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


async def _get_metric_anomalies(args: dict[str, Any]) -> list[TextContent]:
    if pd is None:
        return [TextContent(type="text", text="Error: pandas is required for this tool")]

    k8_object_name = args.get("k8_object_name", "")
    base_dir = args.get("base_dir", "")
    metric_name_filter = args.get("metric_name_filter")
    start_time_str = args.get("start_time")
    end_time_str = args.get("end_time")
    raw_content = args.get("raw_content", True)

    start_time = _parse_time(start_time_str) if start_time_str else None
    end_time = _parse_time(end_time_str) if end_time_str else None

    base_path = Path(base_dir).expanduser()
    if not base_path.exists():
        return [TextContent(type="text", text=f"Metrics directory not found: {base_dir}")]

    # Parse kind and name - supports namespace/kind/name, kind/name, or name formats
    parsed_id = _parse_k8_object_identifier(k8_object_name)

    if parsed_id["format"] == "invalid":
        return [TextContent(type="text", text=parsed_id.get("warning", "Invalid identifier"))]

    kind = parsed_id.get("kind")
    name = parsed_id.get("name", "")

    # Find relevant files
    if not kind:
        # Name-only format - try to find files matching *_{name}*.tsv
        files = list(base_path.glob(f"*_{name}*.tsv"))
        if not files:
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

    if not files:
        return [TextContent(type="text", text=f"No metric files found for {k8_object_name}")]

    results = {"object": k8_object_name, "metrics": []}

    for file_path in files:
        try:
            # Read TSV with pandas
            df = pd.read_csv(file_path, sep="\t")

            # Apply metric name filter
            if metric_name_filter:
                if "metric_name" in df.columns:
                    df = df[df["metric_name"].str.contains(metric_name_filter, na=False)]

                if df.empty:
                    continue

            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

            # Filter by time
            if start_time:
                df = df[df["timestamp"] >= _to_utc_timestamp(start_time)]
            if end_time:
                df = df[df["timestamp"] <= _to_utc_timestamp(end_time)]

            if df.empty:
                continue

            # Calculate stats and anomalies
            # Using simple Z-score on 'value' column
            if "value" in df.columns:
                mean = df["value"].mean()
                std = df["value"].std()

                # If std is 0, no anomalies possible unless we define deviation from mean 0
                anomalies = []
                if std > 0:
                    threshold = mean + 2 * std
                    anomaly_df = df[df["value"] > threshold]
                    anomalies = anomaly_df.to_dict(orient="records")
            else:
                anomalies = []

            # Convert timestamp back to string for JSON serialization
            if "timestamp" in df.columns:
                df["timestamp"] = df["timestamp"].astype(str)
                # Convert anomaly timestamps too
                for a in anomalies:
                    if "timestamp" in a:
                        a["timestamp"] = str(a["timestamp"])

            metric_data = {
                "metric_name": df["metric_name"].iloc[0] if "metric_name" in df.columns else "unknown",
                "file": file_path.name,
                "count": len(df),
                "anomaly_count": len(anomalies),
                "anomalies": anomalies,
            }

            if raw_content:
                metric_data["data"] = df.to_dict(orient="records")

            results["metrics"].append(metric_data)

        except Exception as e:
            results["metrics"].append({"file": file_path.name, "error": str(e)})

    return [TextContent(type="text", text=json.dumps(results, indent=2))]
