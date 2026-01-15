"""
Kubernetes-specific utility functions.
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


def _obj_id(kind: str, name: str, namespace: Optional[str] = None) -> str:
    """Generate a simple, consistent object ID: Kind/name."""
    return f"{kind}/{name}"


def _extract_deployment_from_pod(pod_name: str) -> str:
    """Extract deployment name from pod name.

    Kubernetes pod naming convention: <deployment>-<replicaset-hash>-<pod-hash>
    e.g., frontend-675fd7b5c5-gd8gl -> frontend
          checkout-8546fdc74d-7m4dn -> checkout
    """
    if not pod_name:
        return "unknown"
    parts = pod_name.rsplit("-", 2)
    if len(parts) >= 3:
        return parts[0]
    elif len(parts) == 2:
        return parts[0]
    return pod_name


def _extract_object_info_from_filename(filename: str) -> dict[str, str]:
    """Extract object kind and name from metric filename.

    Filename format: <kind>_<name>.tsv
    e.g., pod_checkout-8546fdc74d-7m4dn.tsv -> {"kind": "pod", "name": "checkout-8546fdc74d-7m4dn"}
    """
    stem = filename.replace(".tsv", "")
    parts = stem.split("_", 1)
    if len(parts) == 2:
        return {"kind": parts[0], "name": parts[1]}
    return {"kind": "unknown", "name": stem}
