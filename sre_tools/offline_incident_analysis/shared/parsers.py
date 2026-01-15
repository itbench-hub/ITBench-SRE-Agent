"""
Parsing utilities for K8s objects, timestamps, and data formats.
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


def _parse_k8_object_identifier(identifier: str) -> dict[str, Any]:
    """Parse a K8s object identifier supporting multiple formats.

    Supported formats (in order of preference):
    1. namespace/kind/name - PREFERRED (most specific, unambiguous)
    2. kind/name - DISCOURAGED (can exist in multiple namespaces)
    3. name - DISCOURAGED (can exist in multiple kinds and namespaces)

    Args:
        identifier: K8s object identifier string

    Returns:
        Dictionary with:
        - namespace: str | None
        - kind: str | None
        - name: str
        - format: "namespace/kind/name" | "kind/name" | "name"
        - is_ambiguous: bool (True for kind/name and name formats)
        - warning: str | None (warning message for ambiguous formats)
    """
    if not identifier:
        return {
            "namespace": None,
            "kind": None,
            "name": "",
            "format": "invalid",
            "is_ambiguous": True,
            "warning": "Empty identifier provided",
        }

    parts = [p.strip() for p in identifier.split("/") if p.strip()]

    if len(parts) >= 3:
        # namespace/kind/name format (preferred)
        # Handle cases where name might contain slashes
        namespace = parts[0]
        kind = parts[1]
        name = "/".join(parts[2:])
        return {
            "namespace": namespace,
            "kind": kind,
            "name": name,
            "format": "namespace/kind/name",
            "is_ambiguous": False,
            "warning": None,
        }
    elif len(parts) == 2:
        # kind/name format (discouraged - ambiguous across namespaces)
        kind = parts[0]
        name = parts[1]
        return {
            "namespace": None,
            "kind": kind,
            "name": name,
            "format": "kind/name",
            "is_ambiguous": True,
            "warning": f"Format 'kind/name' is ambiguous - '{identifier}' may exist in multiple namespaces. Consider using 'namespace/kind/name' format for precision.",
        }
    else:
        # name only format (most ambiguous)
        name = parts[0]
        return {
            "namespace": None,
            "kind": None,
            "name": name,
            "format": "name",
            "is_ambiguous": True,
            "warning": f"Format 'name' is highly ambiguous - '{identifier}' may exist across multiple kinds and namespaces. Consider using 'namespace/kind/name' format for precision.",
        }


def _build_k8_object_filter_mask(
    df: "pd.DataFrame",
    parsed_id: dict[str, Any],
    kind_col: str = "object_kind",
    namespace_col: str = "object_namespace",
    name_col: str = "object_name",
    entity_id_col: str | None = "entity_id",
) -> "pd.Series":
    """Build a pandas filter mask for K8s objects based on parsed identifier.

    For unambiguous identifiers (namespace/kind/name), returns exact match.
    For ambiguous identifiers (kind/name or name), returns ALL matches.

    Args:
        df: DataFrame with K8s object data
        parsed_id: Output from _parse_k8_object_identifier()
        kind_col: Column name for object kind
        namespace_col: Column name for namespace
        name_col: Column name for object name
        entity_id_col: Optional column name for entity_id (for fallback matching)

    Returns:
        Boolean pandas Series mask
    """
    import pandas as pd

    namespace = parsed_id.get("namespace")
    kind = parsed_id.get("kind")
    name = parsed_id.get("name", "")
    fmt = parsed_id.get("format")

    if fmt == "namespace/kind/name":
        # Most specific - exact match on all three
        mask = (
            (df[kind_col].str.lower() == kind.lower())
            & (df[namespace_col].str.lower() == namespace.lower())
            & (df[name_col].str.lower() == name.lower())
        )
    elif fmt == "kind/name":
        # Match kind and name, any namespace (return all matches)
        mask = (df[kind_col].str.lower() == kind.lower()) & (df[name_col].str.lower() == name.lower())
    elif fmt == "name":
        # Match name only, any kind and namespace (return all matches)
        mask = df[name_col].str.lower() == name.lower()
    else:
        # Invalid format - return empty mask
        mask = pd.Series([False] * len(df), index=df.index)

    # If no matches found, try partial/contains match on entity_id as fallback
    if not mask.any() and entity_id_col and entity_id_col in df.columns:
        search_term = name.lower()
        mask = df[entity_id_col].str.lower().str.contains(search_term, na=False)

    return mask


def _get_matched_entities_summary(df: "pd.DataFrame", mask: "pd.Series", entity_id_col: str = "entity_id") -> list[str]:
    """Get a summary of matched entity IDs for reporting."""
    if entity_id_col not in df.columns:
        return []
    matched = df.loc[mask, entity_id_col].unique().tolist()
    return sorted(matched)


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


def _format_k8s_timestamp(ts: "pd.Timestamp | datetime | None") -> str | None:
    """Format a timestamp to K8s-style ISO 8601 format ('2025-12-15T17:26:34Z').

    Returns None if input is None or invalid.
    """
    if ts is None:
        return None
    try:
        if pd is not None and isinstance(ts, pd.Timestamp):
            if pd.isna(ts):
                return None
            # Convert to UTC if timezone-aware, then format
            if ts.tzinfo is not None:
                ts = ts.tz_convert("UTC")
            return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(ts, datetime):
            return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            return None
    except Exception:
        return None


def _parse_duration(duration_str: str) -> timedelta:
    """Parse duration string (e.g., '5m', '1h') to timedelta."""
    if not duration_str:
        return timedelta(minutes=5)

    unit = duration_str[-1]
    value = int(duration_str[:-1])

    if unit == "s":
        return timedelta(seconds=value)
    elif unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    else:
        return timedelta(minutes=5)  # Default


def _parse_otel_event_body(body_str: str) -> dict[str, Any]:
    """Parse OTEL event Body JSON and extract K8s event fields.

    OTEL format wraps K8s events in a JSON structure like:
    {
        "object": {
            "involvedObject": {"kind": "Pod", "name": "...", "namespace": "..."},
            "reason": "Scheduled",
            "message": "...",
            "lastTimestamp": "...",
            "type": "Normal"
        },
        "type": "ADDED"
    }

    Returns flattened dict with standard event columns.
    """
    try:
        body = json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        return {}

    obj = body.get("object", {})
    involved = obj.get("involvedObject", {}) or obj.get("regarding", {})

    return {
        "object_kind": involved.get("kind", ""),
        "object_name": involved.get("name", ""),
        "namespace": involved.get("namespace", ""),
        "reason": obj.get("reason", ""),
        "message": obj.get("message", "") or obj.get("note", ""),
        "event_time": obj.get("lastTimestamp") or obj.get("firstTimestamp") or obj.get("eventTime"),
        "event_kind": obj.get("type", ""),  # Normal, Warning
        "watch_type": body.get("type", ""),  # ADDED, MODIFIED, DELETED
        "count": obj.get("count", 1),
        "source_component": (obj.get("source", {}) or {}).get("component", ""),
    }


def _parse_k8s_body_json(raw: Any) -> dict[str, Any] | None:
    """Parse a Kubernetes object JSON from TSV/OTEL strings.

    Handles:
    - Raw OTEL TSV "Body" where the JSON object is stored as a quoted string with doubled quotes
    - Already-decoded JSON strings (double-encoded)
    - Processed TSV where body is a JSON object string
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None

    s = raw.strip()
    if not s:
        return None

    # Raw TSV may store JSON as quoted string with doubled quotes.
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    s = s.replace('""', '"')

    try:
        obj: Any = json.loads(s)
    except Exception:
        return None

    # Some inputs are double-encoded (JSON string containing JSON object).
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return None

    return obj if isinstance(obj, dict) else None


def _parse_tags_to_dict(tags: Any) -> dict[str, Any]:
    """Parse the `tags` column into a dict.

    Metrics TSVs may store tags as:
    - a dict-like string: "{'k': 'v', ...}"
    - a JSON object string: '{"k":"v"}'
    - already a dict
    """
    if tags is None:
        return {}
    if isinstance(tags, dict):
        return tags
    if not isinstance(tags, str):
        return {}

    s = tags.strip()
    if not s:
        return {}

    # Try JSON first.
    if s.startswith("{") and '"' in s:
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

    # Fallback to python-literal style (repr(dict)).
    try:
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
