"""Entry point for running Agentz as a module.

Usage:
    python -m agentz --scenario-dir /path/to/scenario
    python -m agentz --scenario-dir /path/to/scenario --run-id 1 --model "anthropic/claude-opus-4.5"
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())


