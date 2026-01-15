"""
Statistical utilities for trace analysis.
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


def _compute_percentiles(latencies: List[float]) -> Dict[str, float]:
    """Compute p50, p90, p99 percentiles for a list of latencies."""
    if not latencies:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    return {
        "p50": round(sorted_lat[int(n * 0.50)] if n > 0 else 0, 2),
        "p90": round(sorted_lat[min(int(n * 0.90), n - 1)] if n > 0 else 0, 2),
        "p99": round(sorted_lat[min(int(n * 0.99), n - 1)] if n > 0 else 0, 2),
    }


def _compute_delta(pre_val: float, post_val: float) -> float:
    """Compute percentage change from pre to post value."""
    if pre_val == 0:
        return float("inf") if post_val > 0 else 0.0
    return round((post_val - pre_val) / pre_val * 100, 1)


def _compute_window_summary_compact(
    spans: List[Dict[str, Any]], window_start: datetime, window_end: datetime
) -> Dict[str, Any]:
    """Compute compact summary statistics for a time window."""
    if not spans:
        return None

    trace_ids = set(s.get("trace_id") for s in spans if s.get("trace_id"))
    trace_count = len(trace_ids)
    span_count = len(spans)

    window_duration_sec = (window_end - window_start).total_seconds()
    traffic_rate = round(trace_count / window_duration_sec, 2) if window_duration_sec > 0 else 0

    error_count = sum(1 for s in spans if s.get("status_code") == "Error")
    error_rate_pct = round((error_count / span_count * 100), 2) if span_count > 0 else 0

    latencies = []
    for s in spans:
        try:
            dur = float(s.get("duration_ms", 0))
            latencies.append(dur)
        except (ValueError, TypeError):
            pass

    percentiles = _compute_percentiles(latencies)

    return {"trace_count": trace_count, "error_rate_pct": error_rate_pct, "latency_p99_ms": percentiles["p99"]}
