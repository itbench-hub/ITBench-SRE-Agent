"""
Shared utilities for SRE tools.

Common functions used across multiple MCP tool implementations.
"""

import json
import csv
from pathlib import Path
from typing import Any


def read_json_file(path: str | Path) -> dict[str, Any]:
    """Read and parse a JSON file.
    
    Args:
        path: Path to the JSON file.
        
    Returns:
        Parsed JSON data as dictionary.
        
    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    with open(path, "r") as f:
        return json.load(f)


def read_tsv_file(path: str | Path) -> list[dict[str, str]]:
    """Read and parse a TSV file.
    
    Args:
        path: Path to the TSV file.
        
    Returns:
        List of dictionaries, one per row.
        
    Raises:
        FileNotFoundError: If the file doesn't exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(dict(row))
    
    return rows


def format_timestamp(ts: str | int | float) -> str:
    """Format a timestamp for display.
    
    Args:
        ts: Timestamp as string, int (unix epoch), or float.
        
    Returns:
        Human-readable timestamp string.
    """
    from datetime import datetime
    
    if isinstance(ts, str):
        # Try to parse ISO format
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return ts
    
    if isinstance(ts, (int, float)):
        # Assume unix epoch (seconds or milliseconds)
        if ts > 1e12:  # Likely milliseconds
            ts = ts / 1000
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    
    return str(ts)


def truncate_string(s: str, max_length: int = 500, suffix: str = "...") -> str:
    """Truncate a string to a maximum length.
    
    Args:
        s: String to truncate.
        max_length: Maximum length before truncation.
        suffix: Suffix to add when truncated.
        
    Returns:
        Original or truncated string.
    """
    if len(s) <= max_length:
        return s
    return s[: max_length - len(suffix)] + suffix


def safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely get a nested value from a dictionary.
    
    Args:
        data: Dictionary to traverse.
        *keys: Sequence of keys to follow.
        default: Default value if path doesn't exist.
        
    Returns:
        Value at the path, or default if not found.
        
    Example:
        safe_get(data, "spec", "containers", 0, "name", default="unknown")
    """
    result = data
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key, default)
            if result is default:
                return default
        elif isinstance(result, list) and isinstance(key, int):
            if 0 <= key < len(result):
                result = result[key]
            else:
                return default
        else:
            return default
    return result






