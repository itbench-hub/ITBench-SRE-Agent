"""
Formatting utilities for output data.
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


def _df_to_json_records(df: "pd.DataFrame", *, compact: bool) -> str:
    """Serialize a DataFrame to JSON records.

    Compact mode is intended for LLM consumption (no pretty indentation).
    """
    if compact:
        return df.to_json(orient="records")
    return df.to_json(orient="records", indent=2)


def _format_latency(ms: float) -> str:
    """Format latency in human-readable form."""
    if ms < 1:
        return f"{ms:.2f}ms"
    elif ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        return f"{ms/60000:.1f}m"


def _format_rate(rate: float) -> str:
    """Format rate as X/s."""
    if rate < 1:
        return f"{rate:.2f}/s"
    else:
        return f"{rate:.0f}/s"
