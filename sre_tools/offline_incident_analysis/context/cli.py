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


def _cli_get_context_contract(args) -> int:
    """CLI handler for get_context_contract command."""
    import asyncio

    try:
        # Build arguments dict
        arguments = {
            "k8_object": args.k8_object,
            "snapshot_dir": args.snapshot_dir,
        }
        if args.topology_file:
            arguments["topology_file"] = args.topology_file
        if args.start_time:
            arguments["start_time"] = args.start_time
        if args.end_time:
            arguments["end_time"] = args.end_time
        if args.page is not None:
            arguments["page"] = args.page
        if args.deps_per_page is not None:
            arguments["deps_per_page"] = args.deps_per_page

        # Run async function
        result = asyncio.run(_get_context_contract(arguments))

        # Print result
        for content in result:
            print(content.text)

        return 0
    except FileNotFoundError as e:
        print(f"✗ File not found: {e}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1
