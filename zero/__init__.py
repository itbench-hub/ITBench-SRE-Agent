"""
Zero - A minimal Codex wrapper for reproducible agent runs.

Zero sets up a workspace with proper configuration, prompts, policies,
and sandbox settings, then launches Codex with the workspace as CODEX_HOME.

Usage:
    zero --workspace /path/to/workspace --read-only-dir /path/to/data -- exec --full-auto "prompt"

See `zero --help` for full usage.
"""

__version__ = "0.2.0"
__all__ = ["ZeroWorkspacePaths", "setup_workspace", "run_codex", "OtelTraceCollector"]

from .config import ZeroWorkspacePaths, setup_workspace
from .runner import run_codex
from .tracing import OtelTraceCollector
