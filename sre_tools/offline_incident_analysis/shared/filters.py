"""
Filtering utilities for K8s objects and time-based data.
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


def _filter_by_time(
    records: List[Dict[str, Any]], time_col: str, start: datetime, end: datetime
) -> List[Dict[str, Any]]:
    """Filter records by time range [start, end)."""
    result = []
    for record in records:
        ts_str = record.get(time_col)
        if not ts_str:
            continue
        try:
            ts = _parse_time(ts_str)
            # Make both timezone-aware or both naive for comparison
            if ts.tzinfo is None and start.tzinfo is not None:
                ts = ts.replace(tzinfo=start.tzinfo)
            elif ts.tzinfo is not None and start.tzinfo is None:
                ts = ts.replace(tzinfo=None)
            if start <= ts < end:
                result.append(record)
        except (ValueError, TypeError):
            continue
    return result


def _filter_labels(labels: dict[str, Any], keep: list[str] | None) -> dict[str, Any]:
    """Filter label dict to allowlisted keys."""
    if not labels or not keep:
        return {}
    return {k: labels[k] for k in keep if k in labels}


def _get_matched_entities_summary(df: "pd.DataFrame", mask: "pd.Series", entity_id_col: str = "entity_id") -> list[str]:
    """Get a summary of matched entity IDs for reporting."""
    if entity_id_col not in df.columns:
        return []
    matched = df.loc[mask, entity_id_col].unique().tolist()
    return sorted(matched)
