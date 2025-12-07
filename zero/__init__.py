"""
Zero - A parameterized wrapper for running Codex CLI against incident snapshots.

This module provides a flexible interface to run the Codex agent with 
customizable configuration for SRE incident investigation.

Usage:
    python -m zero --session-dir /path/to/session --read-only-dir /path/to/scenario
    python -m zero --help
"""

__version__ = "0.1.0"
__all__ = ["ZeroConfig", "CodexRunner", "run", "OtelTraceCollector"]

from .config import ZeroConfig
from .runner import CodexRunner, run
from .tracing import OtelTraceCollector
