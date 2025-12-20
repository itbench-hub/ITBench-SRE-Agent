"""CLI entrypoint for ITBench Evaluations."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .agent import evaluate_batch, EvaluationConfig, EVAL_CRITERIA
from .aggregator import calculate_statistics
from .loader import load_ground_truth, load_agent_outputs


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="ITBench Evaluations - LLM-as-a-Judge for RCA evaluation"
    )
    
    parser.add_argument(
        "--ground-truth",
        "-g",
        type=str,
        required=True,
        help=(
            "Path to ground truth. Supports: "
            "(1) Directory with per-scenario subdirs (e.g., ITBench-Snapshots/<id>/ground_truth.yaml), "
            "(2) Single JSON/YAML file with all ground truths"
        ),
    )
    
    parser.add_argument(
        "--outputs",
        "-o",
        type=str,
        required=True,
        help="Path to agent outputs directory",
    )
    
    parser.add_argument(
        "--result-file",
        "-r",
        type=str,
        default="evaluation_results.json",
        help="Output file for results (default: evaluation_results.json)",
    )
    
    parser.add_argument(
        "--eval-criteria",
        "-e",
        type=str,
        nargs="+",
        choices=EVAL_CRITERIA,
        help="Evaluation criteria to use (default: all)",
    )
    
    parser.add_argument(
        "--k",
        type=int,
        default=3,
        help="Value of k for ROOT_CAUSE_ENTITY_K metric (default: 3)",
    )
    
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum concurrent evaluations (default: 5)",
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    return parser.parse_args()


async def main_async(args):
    """Main async entry point."""
    logger = logging.getLogger("itbench_evaluations")
    
    # Load ground truths
    logger.info(f"Loading ground truths from: {args.ground_truth}")
    ground_truths = load_ground_truth(args.ground_truth)
    logger.info(f"Loaded {len(ground_truths)} ground truth scenarios")
    
    # Load agent outputs for each scenario
    logger.info(f"Loading agent outputs from: {args.outputs}")
    all_agent_outputs = {}
    total_trials = 0
    total_bad_runs = 0
    
    for incident_id in ground_truths.keys():
        outputs, bad_runs = await load_agent_outputs(args.outputs, incident_id)
        if outputs:
            all_agent_outputs[incident_id] = outputs
            total_trials += len(outputs)
        total_bad_runs += bad_runs
    
    logger.info(f"Loaded {total_trials} trials across {len(all_agent_outputs)} incidents")
    if total_bad_runs > 0:
        logger.warning(f"Found {total_bad_runs} bad/unreadable runs")
    
    # Create evaluation config
    config = EvaluationConfig(
        eval_criteria=args.eval_criteria,
        k=args.k,
        max_concurrent=args.max_concurrent,
    )
    
    # Run batch evaluation
    logger.info("Starting batch evaluation...")
    results = await evaluate_batch(ground_truths, all_agent_outputs, config)
    
    # Structure results for aggregator
    structured_results = []
    incident_results = {}
    
    for result in results:
        incident_id = result.get("incident_id")
        if incident_id not in incident_results:
            incident_results[incident_id] = {
                "incident_id": incident_id,
                "evaluations": [],
                "total_bad_runs": 0,
            }
        
        incident_results[incident_id]["evaluations"].append({
            "trial_id": result.get("trial_id"),
            "scores": result.get("scores", {}),
        })
    
    structured_results = list(incident_results.values())
    
    # Calculate statistics
    logger.info("Calculating statistics...")
    stats = calculate_statistics(structured_results)
    
    # Prepare output
    output = {
        "raw_results": results,
        "statistics": stats,
        "config": {
            "ground_truth_path": args.ground_truth,
            "outputs_path": args.outputs,
            "eval_criteria": args.eval_criteria or EVAL_CRITERIA,
            "k": args.k,
        },
    }
    
    # Write results
    result_path = Path(args.result_file)
    with open(result_path, "w") as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Results written to: {result_path}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Incidents evaluated: {len(incident_results)}")
    print(f"Total trials: {total_trials}")
    print(f"Bad runs: {total_bad_runs}")
    print("\nOverall Statistics:")
    for metric, metric_stats in stats.get("overall", {}).items():
        if metric == "total_bad_runs":
            continue
        if isinstance(metric_stats, dict):
            mean = metric_stats.get("mean", "N/A")
            stderr = metric_stats.get("stderr", "N/A")
            print(f"  {metric}: mean={mean:.4f}" if isinstance(mean, (int, float)) else f"  {metric}: {mean}")
    print("=" * 60)


def main():
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)
    
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nEvaluation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Evaluation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

