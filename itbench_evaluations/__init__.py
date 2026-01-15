"""ITBench Evaluations - LLM-as-a-Judge for RCA evaluation."""

from .agent import (
    DEFAULT_K_VALUES,
    EVAL_CRITERIA,
    EvaluationConfig,
    LAAJAgent,
    compute_all_k_metrics,
    compute_entity_metrics_at_k,
    evaluate_batch,
    evaluate_single,
)
from .aggregator import calculate_statistics
from .client import create_judge_client, get_judge_model
from .loader import canonicalize_scenario_id, load_agent_outputs, load_ground_truth

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
