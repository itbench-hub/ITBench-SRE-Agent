"""Entry point for running Zero as a module.

Usage:
    python -m zero --session-dir /path/to/session --read-only-dir /path/to/scenario
    python -m zero --session-dir /tmp/session --read-only-dir /path/to/scenario --model "anthropic/claude-opus-4.5"
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
