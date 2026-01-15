"""
Time parsing and handling utilities.
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


def _parse_time(ts: str) -> datetime:
    """Parse timestamp string to datetime object."""
    try:
        # Handle ISO format with Z
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        # Try other formats if needed
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _extract_alert_snapshot_timestamp(json_file: Path, data: Any) -> Optional[str]:
    """Extract observation/snapshot timestamp for an alerts JSON file.

    For alert snapshot dumps, we want *when the alert was observed* (the snapshot time),
    not when it first became active (activeAt).

    Supported formats:
    - alerts_at_YYYY-MM-DDTHH-MM-SS[.ffffff].json (timestamp comes from filename)
    - alerts_in_alerting_state_*.json (timestamp often exists in JSON as top-level 'timestamp')

    Returns an ISO-8601 string with 'Z' suffix when possible.
    """
    if isinstance(data, dict):
        ts = data.get("timestamp")
        if isinstance(ts, str) and ts.strip():
            return ts.strip()

    stem = json_file.stem

    # alerts_at_2025-12-15T18-17-09.387695.json
    m = re.search(
        r"alerts_at_(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})(\.\d+)?",
        stem,
    )
    if m:
        date, hh, mm, ss, frac = m.groups()
        frac = frac or ""
        return f"{date}T{hh}:{mm}:{ss}{frac}Z"

    # alerts_in_alerting_state_2025-12-15T175546.713186Z.json
    m = re.search(
        r"alerts_in_alerting_state_(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})(\.\d+)?Z?",
        stem,
    )
    if m:
        date, hh, mm, ss, frac = m.groups()
        frac = frac or ""
        return f"{date}T{hh}:{mm}:{ss}{frac}Z"

    # Fallback: try to find any YYYY-MM-DDT... token and normalize.
    m = re.search(r"(\d{4}-\d{2}-\d{2})T([^_]+)", stem)
    if not m:
        return None

    date, tail = m.groups()
    tail = tail.rstrip("Z")

    # If the tail uses hyphens as separators: 18-17-09.387695
    if "-" in tail:
        parts = tail.split(".", 1)
        hms = parts[0].replace("-", ":")
        frac = f".{parts[1]}" if len(parts) == 2 and parts[1] else ""
        if len(hms.split(":")) == 3:
            return f"{date}T{hms}{frac}Z"

    # If the tail is a compact time: 175546.713186
    parts = tail.split(".", 1)
    digits = parts[0]
    if digits.isdigit() and len(digits) >= 6:
        hms = f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
        frac = f".{parts[1]}" if len(parts) == 2 and parts[1] else ""
        return f"{date}T{hms}{frac}Z"

    return None


def _to_utc_timestamp(ts) -> "pd.Timestamp":
    """Convert a time value to UTC-aware pandas Timestamp for comparison.

    Handles both timezone-aware and timezone-naive inputs consistently.
    All timestamps are treated as UTC for comparison purposes.
    """
    ts_pd = pd.Timestamp(ts)
    if ts_pd.tzinfo is None:
        return ts_pd.tz_localize("UTC")
    else:
        return ts_pd.tz_convert("UTC")


def _parse_k8s_timestamp(ts_str: str | None) -> "pd.Timestamp | None":
    """Parse a Kubernetes metadata timestamp (ISO 8601 format like '2025-12-14T18:17:52Z').

    Returns a UTC-aware pandas Timestamp, or None if parsing fails.
    """
    if pd is None or not ts_str:
        return None
    try:
        ts = pd.to_datetime(ts_str, errors="coerce", utc=True)
        return ts if pd.notna(ts) else None
    except Exception:
        return None


def _effective_update_timestamp(obj: dict[str, Any]) -> "pd.Timestamp | None":
    """Extract an 'effective update time' from a Kubernetes object.

    This is used to answer: "did this change happen in the window?" even when the
    OTEL k8sobjects snapshot observes the updated object later.

    Heuristics (UTC):
    - max(metadata.managedFields[].time)
    - max(spec.template.metadata.annotations.kubectl.kubernetes.io/restartedAt)
    """
    if pd is None:
        return None

    if not isinstance(obj, dict):
        return None

    candidates: list["pd.Timestamp"] = []

    meta = obj.get("metadata") or {}
    if isinstance(meta, dict):
        managed = meta.get("managedFields") or []
        if isinstance(managed, list):
            for entry in managed:
                if not isinstance(entry, dict):
                    continue
                t = entry.get("time")
                if not t:
                    continue
                ts = pd.to_datetime(t, errors="coerce", utc=True)
                if pd.notna(ts):
                    candidates.append(ts)

    # kubectl rollout restart often annotates this timestamp on the pod template
    restarted_at = None
    try:
        restarted_at = (
            (obj.get("spec") or {})
            .get("template", {})
            .get("metadata", {})
            .get("annotations", {})
            .get("kubectl.kubernetes.io/restartedAt")
        )
    except Exception:
        restarted_at = None

    if restarted_at:
        ts = pd.to_datetime(restarted_at, errors="coerce", utc=True)
        if pd.notna(ts):
            candidates.append(ts)

    if not candidates:
        return None

    return max(candidates)
