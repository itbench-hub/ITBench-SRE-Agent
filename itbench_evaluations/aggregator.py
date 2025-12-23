"""Statistics aggregation for ITBench Evaluations."""

from typing import Any, Dict, List

import numpy as np
from scipy import stats as scipystats


def calculate_statistics(all_incidents_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate pass@1, mean, and standard error for each metric.
    
    Calculates statistics per incident and overall (macro-averaged).
    
    Args:
        all_incidents_results: List of incident results, each containing:
            - incident_id: str
            - evaluations: List of evaluation dicts with "scores" key
            - total_bad_runs: int (optional)
    
    Returns:
        Dict with "per_incident" and "overall" statistics
    """
    stats = {
        "per_incident": {},
        "overall": {}
    }
    
    total_bad_runs = 0
    all_trials_scores = []
    
    # Define metric names
    metric_names = [
        "root_cause_entity", 
        "root_cause_entity_k",
        "root_cause_reasoning", 
        "propagation_chain",
        "fault_localization_component_identification",
        "root_cause_reasoning_partial", 
        "root_cause_proximity_no_fp",
        "root_cause_proximity_with_fp"
    ]
    
    # Metrics that should have pass@1 calculated
    pass_at_1_metrics = [
        "root_cause_entity",
        "root_cause_entity_k", 
        "fault_localization_component_identification"
    ]
    
    # Full list of metric keys including precision/recall/f1 variants
    metric_keys = [
        "root_cause_entity_precision", 
        "root_cause_entity_recall",
        "root_cause_entity_f1",
        "root_cause_entity_k_precision", 
        "root_cause_entity_k_recall",
        "root_cause_entity_k_f1",
        "root_cause_reasoning", 
        "propagation_chain",
        "fault_localization_component_identification",
        "root_cause_reasoning_partial", 
        "root_cause_proximity_no_fp_precision",
        "root_cause_proximity_no_fp_recall",
        "root_cause_proximity_no_fp_f1",
        "root_cause_proximity_with_fp_precision",
        "root_cause_proximity_with_fp_recall",
        "root_cause_proximity_with_fp_f1"
    ]
    
    for incident_result in all_incidents_results:
        incident_id = incident_result["incident_id"]
        incident_scores = {metric: [] for metric in metric_keys}
        total_bad_runs += incident_result.get("total_bad_runs", 0)
        
        for evaluation in incident_result.get("evaluations", []):
            scores = evaluation.get("scores")
            if not scores:
                continue
            
            for metric in metric_names:
                metric_data = scores.get(metric)
                if isinstance(metric_data, dict):
                    # Handle different calculation field names
                    for value_key in ['calculation', 'calculation_precision', 'calculation_recall', 'calculation_f1']:
                        score = metric_data.get(value_key)
                        if score is not None:
                            if value_key in ['calculation_precision', 'calculation_recall', 'calculation_f1']:
                                suffix = value_key.split('_')[1]
                                incident_scores[f"{metric}_{suffix}"].append(score)
                            else:
                                incident_scores[metric].append(score)
                elif isinstance(metric_data, (int, float)):
                    # Direct numeric score
                    incident_scores[metric].append(metric_data)
        
        all_trials_scores.append(incident_scores)
        
        # Calculate per-incident statistics
        incident_stats = {}
        for metric in metric_keys:
            scores_list = incident_scores[metric]
            if not scores_list:
                continue
            
            n = len(scores_list)
            metric_stats = {
                "mean": float(np.mean(scores_list)),
                "stderr": float(np.std(scores_list) / np.sqrt(n)) if n > 0 else 0,
                "n": n,
            }
            
            # Calculate pass@1 for applicable metrics
            if metric in pass_at_1_metrics:
                pass_at_1 = len([s for s in scores_list if s == 1]) / n
                metric_stats["pass@1"] = pass_at_1
            
            incident_stats[metric] = metric_stats
        
        stats["per_incident"][incident_id] = incident_stats
    
    # Calculate overall (macro-averaged) statistics
    overall_scores = {metric: [] for metric in metric_keys}
    for incident_scores in all_trials_scores:
        for metric in metric_keys:
            overall_scores[metric].extend(incident_scores[metric])
    
    overall_stats = {}
    for metric in metric_keys:
        metric_means = []
        metric_pass_at_1s = []
        
        # Collect stats from each incident
        for incident_id, incident_data in stats["per_incident"].items():
            if metric not in incident_data:
                continue
            
            metric_stats = incident_data[metric]
            metric_means.append(metric_stats["mean"])
            
            if metric in pass_at_1_metrics and "pass@1" in metric_stats:
                metric_pass_at_1s.append(metric_stats["pass@1"])
        
        # Macro average = average of incident-level metrics
        if metric_means:
            overall_stats[metric] = {
                "mean": float(np.mean(metric_means)),
                "stderr": float(scipystats.sem(metric_means)) if len(metric_means) > 1 else None,
                "n_incidents": len(metric_means),
            }
            if metric in pass_at_1_metrics and metric_pass_at_1s:
                overall_stats[metric]["pass@1"] = float(np.mean(metric_pass_at_1s))
    
    stats["overall"] = overall_stats
    stats["overall"]["total_bad_runs"] = total_bad_runs
    
    return stats


