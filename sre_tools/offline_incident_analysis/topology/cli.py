"""
CLI command implementations.
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

from .builder import build_topology_standalone


def _cli_build_topology(args) -> int:
    """CLI handler for build_topology command."""
    try:
        topology = build_topology_standalone(
            arch_file=args.arch_file, k8s_objects_file=args.k8s_objects_file, output_file=args.output_file
        )
        print(f"✓ Topology written to {args.output_file}")
        print(f"  Nodes: {len(topology['nodes'])}")
        print(f"  Edges: {len(topology['edges'])}")
        return 0
    except FileNotFoundError as e:
        print(f"✗ File not found: {e}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1
