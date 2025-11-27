"""Entry point for running the SRE Support Agent as a module.

Usage:
    python -m sre_support_agent "Diagnose the incident"
    python -m sre_support_agent "Investigate high latency alerts"
"""

import asyncio

from .main import main

if __name__ == "__main__":
    asyncio.run(main())

