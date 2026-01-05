"""Namespace filtering for entity metrics.

Filters out entities from infrastructure/observability namespaces
that should not be considered as root cause candidates.

These namespaces contain monitoring, logging, and infrastructure components
that observe the system but don't cause application-level failures.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

# Default namespaces to exclude from root cause evaluation
# These are infrastructure/observability namespaces, not application namespaces
DEFAULT_EXCLUDED_NAMESPACES: Set[str] = {
    "kube-system",
    "data-recorders",
    "clickhouse",
    "clickhouse-operator",
    "prometheus",
    "opentelemetry-operator",
    "opentelemetry-collectors",
    "metrics-server",
    "opensearch",
}

# K values for entity@k metrics
K_VALUES = [1, 2, 3, 4, 5]


def extract_namespace(entity_name: str) -> str:
    """Extract namespace from entity name in 'namespace/Kind/name' format.
    
    Args:
        entity_name: Entity name like 'otel-demo/Service/frontend'
        
    Returns:
        Namespace string, or empty string if format doesn't match
    """
    if not entity_name:
        return ""
    parts = entity_name.split("/")
    if len(parts) >= 2:
        return parts[0]
    return ""


def filter_predicted_entities(
    predicted_entities: List[Dict[str, Any]],
    excluded_namespaces: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Filter out entities from excluded namespaces.
    
    Args:
        predicted_entities: List of predicted entity dicts with 'entity' key
        excluded_namespaces: Set of namespace names to exclude (default: DEFAULT_EXCLUDED_NAMESPACES)
        
    Returns:
        Filtered list of predicted entities (preserves order)
    """
    if excluded_namespaces is None:
        excluded_namespaces = DEFAULT_EXCLUDED_NAMESPACES
    
    filtered = []
    for entity in predicted_entities:
        entity_name = entity.get("entity", "")
        namespace = extract_namespace(entity_name)
        if namespace not in excluded_namespaces:
            filtered.append(entity)
    
    return filtered


def recalculate_entity_metrics(
    predicted_entities: List[Dict[str, Any]],
    gt_count: int,
) -> Dict[str, float]:
    """Recalculate precision, recall, F1 from per-entity matches.
    
    Args:
        predicted_entities: List with 'matches_gt' boolean and optional 'matched_to' for each entity
        gt_count: Number of ground truth entities
        
    Returns:
        Dict with 'precision', 'recall', 'f1' scores
        
    Note:
        - Precision = correct predictions / total predictions
        - Recall = unique GT entities found / total GT entities
        - Multiple predictions can match the same GT entity, but for recall
          we only count each GT entity once.
    """
    if not predicted_entities or gt_count <= 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    # Count correct predictions for precision
    tp = sum(1 for e in predicted_entities if e.get("matches_gt", False))
    
    # Count UNIQUE GT entities found for recall
    # Use 'matched_to' field if available, otherwise just count matches
    unique_gt_matched: Set[str] = set()
    for e in predicted_entities:
        if e.get("matches_gt", False):
            matched_to = e.get("matched_to")
            if matched_to:
                unique_gt_matched.add(matched_to)
            else:
                # If no matched_to field, count as 1 match (legacy behavior)
                unique_gt_matched.add(f"_match_{len(unique_gt_matched)}")
    
    precision = tp / len(predicted_entities) if len(predicted_entities) > 0 else 0.0
    recall = len(unique_gt_matched) / gt_count
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {"precision": precision, "recall": recall, "f1": f1}


def recalculate_entity_metrics_at_k(
    predicted_entities: List[Dict[str, Any]],
    gt_count: int,
    k: int,
) -> Dict[str, float]:
    """Recalculate precision, recall, F1 for top-k entities.
    
    Args:
        predicted_entities: List with 'matches_gt' boolean for each entity
        gt_count: Number of ground truth entities
        k: Number of top predictions to consider
        
    Returns:
        Dict with 'precision', 'recall', 'f1' scores
    """
    if k <= 0 or gt_count <= 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    top_k = predicted_entities[:k]
    return recalculate_entity_metrics(top_k, gt_count)


def apply_namespace_filter_to_scores(
    eval_result: Dict[str, Any],
    excluded_namespaces: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Apply namespace filtering and recalculate all entity-related scores.
    
    This function reads the per-entity match data from eval_result, filters out
    entities from excluded namespaces, and recalculates precision/recall/F1.
    
    Args:
        eval_result: The eval_result dict from judge_output.json
        excluded_namespaces: Set of namespaces to exclude (default: DEFAULT_EXCLUDED_NAMESPACES)
        
    Returns:
        Dict of flat scores with recalculated entity metrics.
        Only includes entity-related metrics (root_cause_entity_*).
        Returns empty dict if eval_result doesn't have required data.
    """
    if excluded_namespaces is None:
        excluded_namespaces = DEFAULT_EXCLUDED_NAMESPACES
    
    scores = eval_result.get("scores", {})
    root_cause_entity = scores.get("root_cause_entity", {})
    
    if not isinstance(root_cause_entity, dict):
        return {}
    
    predicted_entities = root_cause_entity.get("predicted_entities", [])
    gt_entities = root_cause_entity.get("gt_entities", [])
    
    if not predicted_entities:
        return {}
    
    gt_count = len(gt_entities)
    
    # Filter predicted entities by namespace
    filtered_entities = filter_predicted_entities(predicted_entities, excluded_namespaces)
    
    # Recalculate base metrics
    base_metrics = recalculate_entity_metrics(filtered_entities, gt_count)
    
    # Build flat scores for entity metrics
    flat_scores: Dict[str, Any] = {
        "root_cause_entity_precision": base_metrics["precision"],
        "root_cause_entity_recall": base_metrics["recall"],
        "root_cause_entity_f1": base_metrics["f1"],
    }
    
    # Recalculate @k metrics for each k value
    for k in K_VALUES:
        k_metrics = recalculate_entity_metrics_at_k(filtered_entities, gt_count, k)
        flat_scores[f"root_cause_entity_k@{k}_precision"] = k_metrics["precision"]
        flat_scores[f"root_cause_entity_k@{k}_recall"] = k_metrics["recall"]
        flat_scores[f"root_cause_entity_k@{k}_f1"] = k_metrics["f1"]
    
    # Legacy k=3 format for backward compatibility
    k3_metrics = recalculate_entity_metrics_at_k(filtered_entities, gt_count, 3)
    flat_scores["root_cause_entity_k_precision"] = k3_metrics["precision"]
    flat_scores["root_cause_entity_k_recall"] = k3_metrics["recall"]
    flat_scores["root_cause_entity_k_f1"] = k3_metrics["f1"]
    
    return flat_scores


def get_filtering_summary(
    eval_result: Dict[str, Any],
    excluded_namespaces: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Get a summary of what was filtered for debugging/logging.
    
    Args:
        eval_result: The eval_result dict from judge_output.json
        excluded_namespaces: Set of namespaces to exclude
        
    Returns:
        Dict with filtering summary including counts and filtered entity names
    """
    if excluded_namespaces is None:
        excluded_namespaces = DEFAULT_EXCLUDED_NAMESPACES
    
    scores = eval_result.get("scores", {})
    root_cause_entity = scores.get("root_cause_entity", {})
    
    if not isinstance(root_cause_entity, dict):
        return {"original_count": 0, "filtered_count": 0, "removed_entities": []}
    
    predicted_entities = root_cause_entity.get("predicted_entities", [])
    filtered_entities = filter_predicted_entities(predicted_entities, excluded_namespaces)
    
    removed = []
    for entity in predicted_entities:
        entity_name = entity.get("entity", "")
        namespace = extract_namespace(entity_name)
        if namespace in excluded_namespaces:
            removed.append(entity_name)
    
    return {
        "original_count": len(predicted_entities),
        "filtered_count": len(filtered_entities),
        "removed_entities": removed,
        "excluded_namespaces": list(excluded_namespaces),
    }

