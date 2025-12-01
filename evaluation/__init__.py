"""
LAAJ (LLM-as-a-Judge) Evaluation Module.

This module provides evaluation capabilities for SRE agent outputs using
an LLM-based judge to score root cause analysis performance.
"""

from .laaj import LAAJEvaluator, evaluate_agent_output
from .prompts import LAAJ_SYSTEM_PROMPT, EVALUATE_PROMPT_TEMPLATE

__all__ = [
    "LAAJEvaluator",
    "evaluate_agent_output",
    "LAAJ_SYSTEM_PROMPT",
    "EVALUATE_PROMPT_TEMPLATE",
]



