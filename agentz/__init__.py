"""
Agentz - A parameterized wrapper for running Codex CLI against incident snapshots.

This module provides a flexible interface to run the Codex agent with 
customizable configuration for SRE incident investigation.

Usage:
    python -m agentz --scenario-dir /path/to/scenario --run-id 1
    python -m agentz --help
"""

__version__ = "0.1.0"
__all__ = ["AgentZConfig", "CodexRunner", "run", "OtelTraceCollector"]

from .config import AgentZConfig
from .runner import CodexRunner, run
from .tracing import OtelTraceCollector

