#!/usr/bin/env python3
"""
Re-evaluate agent outputs using LLM-as-a-Judge.

Use this when:
- Judge failed due to network issues (timeout, proxy not connected)
- You want to re-score existing agent outputs with a different judge model
- You need to recalculate metrics after fixing evaluation bugs

Examples:
  # Re-evaluate specific scenarios for a result file
  python reeval_judge.py \
    --result-file website/results/result_openrouter_anthropic_claude-opus-4.5_agentz-code_7df3f73-dirty.json \
    --scenarios-dir ITBench-Snapshots/snapshots/sre/v0.1-ca9707b2-8b70-468b-a8f9-9658438f80b1 \
    --scenarios Scenario-1 Scenario-102

  # Re-evaluate all scenarios that have errors
  python reeval_judge.py \
    --result-file website/results/result_xxx.json \
    --scenarios-dir ITBench-Snapshots/snapshots/sre/v0.1-ca9707b2-8b70-468b-a8f9-9658438f80b1 \
    --failed-only

  # Use a different judge model
  python reeval_judge.py \
    --result-file website/results/result_xxx.json \
    --scenarios-dir ITBench-Snapshots/snapshots/sre/v0.1-ca9707b2-8b70-468b-a8f9-9658438f80b1 \
    --scenarios Scenario-1 \
    --judge-model openai/gpt-4o
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from evaluation import LAAJEvaluator

# Metric names for stats calculation
METRIC_NAMES = [
    "root_cause_entity",
    "root_cause_reasoning",
    "propagation_chain",
    "root_cause_reasoning_partial",
    "root_cause_proximity_no_fp",
    "root_cause_proximity_with_fp",
]


def load_ground_truth(scenario_name: str, scenarios_dir: Path) -> Optional[Dict]:
    """Load ground truth for a scenario.
    
    Args:
        scenario_name: Name of the scenario (e.g., Scenario-1)
        scenarios_dir: Directory containing scenario folders with ground_truth.yaml
    """
    scenario_dir = scenarios_dir / scenario_name
    gt_path = scenario_dir / "ground_truth.yaml"
    
    if gt_path.exists():
        with open(gt_path, "r") as f:
            return yaml.safe_load(f)
    
    return None


def load_agent_output(raw_dir: Path, scenario_name: str, run_num: int) -> Optional[Any]:
    """Load agent output for a specific run."""
    output_file = raw_dir / scenario_name / str(run_num) / "agent_output.json"
    
    if not output_file.exists():
        return None
    
    try:
        with open(output_file, "r") as f:
            content = f.read().strip()
        
        if not content:
            return None
        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Return raw content - LLM judge can still evaluate it
            return content
    except Exception as e:
        print(f"  ⚠️  Failed to read agent output: {e}")
        return None


def calculate_metric_stats(runs: List[Dict]) -> Dict[str, Dict[str, float]]:
    """Calculate average, min, max for each metric across all runs."""
    if not runs:
        return {name: {"avg": 0, "min": 0, "max": 0} for name in METRIC_NAMES}
    
    metric_stats = {}
    for metric_name in METRIC_NAMES:
        values = [run.get("metrics", {}).get(metric_name, 0) for run in runs if run.get("metrics")]
        metric_stats[metric_name] = {
            "avg": sum(values) / len(values) if values else 0,
            "min": min(values) if values else 0,
            "max": max(values) if values else 0,
        }
    
    return metric_stats


def calculate_duration_stats(runs: List[Dict]) -> Dict[str, float]:
    """Calculate average, min, max duration across all runs."""
    durations = [run.get("duration_seconds", 0) for run in runs if run.get("duration_seconds")]
    
    if not durations:
        return {"avg": 0, "min": 0, "max": 0}
    
    return {
        "avg": sum(durations) / len(durations),
        "min": min(durations),
        "max": max(durations),
    }


def calculate_inference_stats(runs: List[Dict]) -> Dict[str, float]:
    """Calculate inference count stats across all runs."""
    counts = [run.get("inference_count", 0) for run in runs if run.get("inference_count")]
    
    if not counts:
        return {"avg": 0, "min": 0, "max": 0, "total": 0}
    
    return {
        "avg": sum(counts) / len(counts),
        "min": min(counts),
        "max": max(counts),
        "total": sum(counts),
    }


def recalculate_summary(results: Dict) -> Dict:
    """Recalculate the summary statistics from scenario data."""
    total_scores = []
    all_durations = []
    all_inferences = []
    
    for scenario_data in results["scenarios"].values():
        scores = scenario_data.get("scores", [])
        total_scores.extend(scores)
        
        for run in scenario_data.get("runs", []):
            if run.get("duration_seconds"):
                all_durations.append(run["duration_seconds"])
            if run.get("inference_count"):
                all_inferences.append(run["inference_count"])
    
    # Calculate overall metric averages
    overall_metric_avgs = {}
    for metric_name in METRIC_NAMES:
        values = []
        for s in results["scenarios"].values():
            for run in s.get("runs", []):
                if run.get("metrics") and metric_name in run["metrics"]:
                    val = run["metrics"][metric_name]
                    if val is not None:
                        values.append(val)
        overall_metric_avgs[metric_name] = sum(values) / len(values) if values else 0
    
    return {
        "total_scenarios": len(results["scenarios"]),
        "total_runs": len(total_scores),
        "overall_avg_score": sum(total_scores) / len(total_scores) if total_scores else 0,
        "overall_min_score": min(total_scores) if total_scores else 0,
        "overall_max_score": max(total_scores) if total_scores else 0,
        "scenarios_with_perfect_score": sum(1 for s in results["scenarios"].values() if s.get("max_score") == 100),
        "scenarios_with_any_success": sum(1 for s in results["scenarios"].values() if s.get("max_score", 0) > 0),
        "metric_averages": overall_metric_avgs,
        "duration": {
            "avg": sum(all_durations) / len(all_durations) if all_durations else 0,
            "min": min(all_durations) if all_durations else 0,
            "max": max(all_durations) if all_durations else 0,
            "total": sum(all_durations),
        },
        "inferences": {
            "avg": sum(all_inferences) / len(all_inferences) if all_inferences else 0,
            "min": min(all_inferences) if all_inferences else 0,
            "max": max(all_inferences) if all_inferences else 0,
            "total": sum(all_inferences),
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Re-evaluate agent outputs using LLM-as-a-Judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument("--result-file", "-f", required=True,
                        help="Path to the result JSON file to update")
    parser.add_argument("--scenarios", "-s", nargs="+",
                        help="Specific scenarios to re-evaluate (e.g., Scenario-1 Scenario-102)")
    parser.add_argument("--runs", "-r", nargs="+", type=int,
                        help="Specific run numbers to re-evaluate (e.g., 1 2 3)")
    parser.add_argument("--failed-only", action="store_true",
                        help="Only re-evaluate runs that have errors or score=0")
    
    # Scenarios directory
    parser.add_argument("--scenarios-dir", required=True,
                        help="Directory containing scenario folders with ground_truth.yaml "
                             "(e.g., ITBench-Snapshots/snapshots/sre/v0.1-xxx)")
    
    # Judge configuration
    parser.add_argument("--judge-model", default=None,
                        help="Judge model (default: use existing from result file)")
    parser.add_argument("--judge-base-url", default="https://openrouter.ai/api/v1",
                        help="Base URL for judge API")
    parser.add_argument("--judge-api-key",
                        help="API key for judge (default: OPENROUTER_API_KEY)")
    
    # Output
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be re-evaluated without actually doing it")
    parser.add_argument("--backup", action="store_true",
                        help="Create a backup of the result file before modifying")
    
    args = parser.parse_args()
    
    # Load result file
    result_path = Path(args.result_file)
    if not result_path.exists():
        print(f"❌ Result file not found: {result_path}")
        sys.exit(1)
    
    with open(result_path, "r") as f:
        results = json.load(f)
    
    # Determine raw output directory from result file
    project_root = Path(__file__).parent
    model_provider = results.get("model_provider", "")
    model = results.get("model", "")
    version_tag = results.get("version_tag", "")
    
    run_identifier = f"{model_provider}_{model}_{version_tag}".replace("/", "_")
    raw_dir = project_root / "website" / "results" / "raw" / run_identifier
    
    if not raw_dir.exists():
        print(f"❌ Raw output directory not found: {raw_dir}")
        print(f"   Looking for agent outputs in this location.")
        sys.exit(1)
    
    print(f"📂 Raw outputs: {raw_dir}")
    
    # Scenarios directory (contains ground truth)
    scenarios_dir = Path(args.scenarios_dir)
    if not scenarios_dir.exists():
        print(f"❌ Scenarios directory not found: {scenarios_dir}")
        sys.exit(1)
    print(f"📂 Ground truth: {scenarios_dir}")
    
    # Judge configuration
    judge_model = args.judge_model or results.get("judge_model", "google/gemini-2.5-pro")
    judge_api_key = (
        args.judge_api_key or
        os.environ.get("OPENROUTER_API_KEY") or
        os.environ.get("OR_API_KEY")
    )
    
    if not judge_api_key:
        print("❌ Judge API key required. Set --judge-api-key or OPENROUTER_API_KEY")
        sys.exit(1)
    
    # Determine which scenarios/runs to re-evaluate
    scenarios_to_eval = []
    
    for scenario_name, scenario_data in results.get("scenarios", {}).items():
        # Filter by scenario name if specified
        if args.scenarios and scenario_name not in args.scenarios:
            continue
        
        runs_to_eval = set()
        for run_data in scenario_data.get("runs", []):
            run_num = run_data.get("run", 0)
            
            # Filter by run number if specified
            if args.runs and run_num not in args.runs:
                continue
            
            # Filter by failed-only if specified
            if args.failed_only:
                has_error = run_data.get("error") is not None
                has_zero_score = run_data.get("score", 0) == 0
                no_metrics = not run_data.get("metrics")
                
                if not (has_error or has_zero_score or no_metrics):
                    continue
            
            runs_to_eval.add(run_num)
        
        if runs_to_eval:
            scenarios_to_eval.append((scenario_name, sorted(runs_to_eval)))
    
    if not scenarios_to_eval:
        print("✅ No runs to re-evaluate based on filters")
        sys.exit(0)
    
    # Show what will be re-evaluated
    print(f"\n🔍 Will re-evaluate:")
    total_runs = 0
    for scenario_name, runs in scenarios_to_eval:
        print(f"   {scenario_name}: runs {runs}")
        total_runs += len(runs)
    print(f"   Total: {total_runs} run(s)")
    print(f"   Judge: {judge_model}")
    
    if args.dry_run:
        print("\n⚠️  Dry run - no changes made")
        sys.exit(0)
    
    # Backup if requested
    if args.backup:
        backup_path = result_path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(backup_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n💾 Backup saved to: {backup_path}")
    
    # Initialize evaluator
    evaluator = LAAJEvaluator(
        model=judge_model,
        base_url=args.judge_base_url,
        api_key=judge_api_key,
    )
    
    print(f"\n{'='*60}")
    print("🔄 Re-evaluating...")
    print(f"{'='*60}")
    
    # Re-evaluate each run
    for scenario_name, runs in scenarios_to_eval:
        print(f"\n📁 {scenario_name}")
        
        # Load ground truth
        ground_truth = load_ground_truth(scenario_name, scenarios_dir)
        if not ground_truth:
            print(f"   ⚠️  Ground truth not found, skipping")
            continue
        
        scenario_data = results["scenarios"][scenario_name]
        
        for run_num in runs:
            print(f"   🔄 Run {run_num}...", end=" ", flush=True)
            
            # Load agent output
            agent_output = load_agent_output(raw_dir, scenario_name, run_num)
            if not agent_output:
                print("❌ No agent output")
                continue
            
            # Run evaluation
            try:
                eval_result = evaluator.evaluate(ground_truth, agent_output)
                
                score = eval_result.get("score", 0)
                metrics = eval_result.get("metrics", {})
                error = eval_result.get("error")
                
                # Find and update the run in results
                for i, run_data in enumerate(scenario_data["runs"]):
                    if run_data.get("run") == run_num:
                        # Update run data
                        run_data["score"] = score
                        run_data["metrics"] = metrics
                        run_data["justification"] = eval_result.get("justification", "")
                        run_data["error"] = error
                        
                        # Update agent_entities if available
                        if isinstance(agent_output, dict) and "entities" in agent_output:
                            run_data["agent_entities"] = agent_output["entities"]
                        
                        # Update score in scores array
                        if i < len(scenario_data.get("scores", [])):
                            scenario_data["scores"][i] = score
                        
                        break
                
                icon = "✅" if score == 100 else "⚠️" if score > 0 else "❌"
                print(f"{icon} Score: {score}")
                
                # Show error details if evaluation failed
                if error:
                    print(f"      Error: {error}")
                
            except Exception as e:
                import traceback
                print(f"❌ Error: {e}")
                traceback.print_exc()
        
        # Recalculate scenario statistics
        scores = [r.get("score", 0) for r in scenario_data["runs"]]
        scenario_data["scores"] = scores
        scenario_data["avg_score"] = sum(scores) / len(scores) if scores else 0
        scenario_data["min_score"] = min(scores) if scores else 0
        scenario_data["max_score"] = max(scores) if scores else 0
        scenario_data["metric_stats"] = calculate_metric_stats(scenario_data["runs"])
        scenario_data["duration_stats"] = calculate_duration_stats(scenario_data["runs"])
        scenario_data["inference_stats"] = calculate_inference_stats(scenario_data["runs"])
    
    # Recalculate summary
    results["summary"] = recalculate_summary(results)
    results["reeval_timestamp"] = datetime.now().isoformat()
    results["reeval_judge_model"] = judge_model
    
    # Save updated results
    with open(result_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*60}")
    print("✅ Re-evaluation complete!")
    print(f"{'='*60}")
    print(f"   Updated: {result_path}")
    print(f"   Overall avg score: {results['summary']['overall_avg_score']:.2f}")
    print(f"   Root cause entity: {results['summary']['metric_averages']['root_cause_entity']:.2f}")


if __name__ == "__main__":
    main()

