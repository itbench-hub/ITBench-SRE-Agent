"""ITBench Evaluations - LLM-as-a-Judge for RCA evaluation."""

from .agent import (
    LAAJAgent,
    evaluate_single,
    evaluate_batch,
    EvaluationConfig,
    EVAL_CRITERIA,
    DEFAULT_K_VALUES,
    compute_entity_metrics_at_k,
    compute_all_k_metrics,
)
from .aggregator import calculate_statistics
from .loader import load_ground_truth, load_agent_outputs, canonicalize_scenario_id
from .client import create_judge_client, get_judge_model

__all__ = [
    "LAAJAgent",
    "evaluate_single",
    "evaluate_batch",
    "EvaluationConfig",
    "EVAL_CRITERIA",
    "DEFAULT_K_VALUES",
    "compute_entity_metrics_at_k",
    "compute_all_k_metrics",
    "calculate_statistics",
    "load_ground_truth",
    "load_agent_outputs",
    "canonicalize_scenario_id",
    "create_judge_client",
    "get_judge_model",
]


