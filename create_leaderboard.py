#!/usr/bin/env python3
"""
Create Leaderboard - Evaluate Agentz on ITBench scenarios.

This script runs the agentz agent on all ITBench scenarios, evaluates the results
using an LLM-as-judge, and generates a leaderboard result file.

Uses OTEL traces to track execution duration and inference counts.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from evaluation import LAAJEvaluator


# ============================================================================
# Trace Analysis
# ============================================================================

def _clean_event_name(name: str) -> str:
    """Clean up event name from protobuf extraction artifacts.
    
    Protobuf encodes strings with length prefixes, which can appear as
    trailing digits/characters when doing naive string extraction.
    E.g., 'codex.api_request2' -> 'codex.api_request'
    """
    # Known Codex OTEL event names
    known_events = [
        "codex.conversation_starts",
        "codex.api_request", 
        "codex.sse_event",
        "codex.user_prompt",
        "codex.tool_decision",
        "codex.tool_result",
    ]
    
    # Check if the name starts with a known event
    for event in known_events:
        if name.startswith(event):
            return event
    
    # Fallback: strip trailing digits and special chars
    cleaned = re.sub(r'[0-9]+[-\x00-\x1f]*$', '', name)
    return cleaned if cleaned else name


def parse_traces(traces_file: Path) -> Dict[str, Any]:
    """
    Parse OTEL traces from JSONL file and extract metrics.
    
    Returns:
        Dict with:
        - inference_count: Number of API requests
        - total_duration_ms: Total duration from traces
        - token_usage: Token counts if available
    """
    metrics = {
        "inference_count": 0,
        "total_duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    # Track events internally but don't include in output
    _events = []
    
    if not traces_file.exists():
        return metrics
    
    try:
        with open(traces_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    
                    # Extract event info from extracted_strings
                    extracted = record.get("extracted_strings", [])
                    
                    # Count API requests (inferences)
                    for i, s in enumerate(extracted):
                        if s == "event.name" and i + 1 < len(extracted):
                            event_name = _clean_event_name(extracted[i + 1])
                            _events.append(event_name)  # Track internally
                            
                            if "api_request" in event_name:
                                metrics["inference_count"] += 1
                        
                        # Extract duration - look for patterns like "duration_ms" followed by a number
                        if s == "duration_ms" and i + 1 < len(extracted):
                            try:
                                # Try to extract numeric value from next string
                                duration_str = extracted[i + 1]
                                # Extract leading digits
                                match = re.match(r'^(\d+)', duration_str)
                                if match:
                                    duration = int(match.group(1))
                                    metrics["total_duration_ms"] += duration
                            except (ValueError, TypeError):
                                pass
                        
                        # Extract token counts - try multiple patterns
                        # Codex OTEL uses: input_token_count, output_token_count, cached_token_count
                        s_lower = s.lower()
                        if any(x in s_lower for x in ["input_token_count", "input_token", "prompt_token"]) and i + 1 < len(extracted):
                            try:
                                match = re.match(r'^(\d+)', extracted[i + 1])
                                if match:
                                    metrics["input_tokens"] += int(match.group(1))
                            except (ValueError, TypeError):
                                pass
                        if any(x in s_lower for x in ["output_token_count", "output_token", "completion_token"]) and i + 1 < len(extracted):
                            try:
                                match = re.match(r'^(\d+)', extracted[i + 1])
                                if match:
                                    metrics["output_tokens"] += int(match.group(1))
                            except (ValueError, TypeError):
                                pass
                                
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  ⚠️  Error parsing traces: {e}")
    
    return metrics


# ============================================================================
# Utility Functions
# ============================================================================

def load_ground_truth(scenario_path: Path) -> Optional[Dict]:
    """Load ground truth YAML file from scenario directory."""
    gt_path = scenario_path / "ground_truth.yaml"
    if not gt_path.exists():
        print(f"  ⚠️  No ground_truth.yaml found in {scenario_path}")
        return None
    
    try:
        with open(gt_path, "r") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"  ⚠️  Failed to parse ground_truth.yaml: {e}")
        return None


def load_agent_output(output_file: Path) -> Optional[Dict]:
    """Load agent output JSON file."""
    if not output_file.exists():
        return None
    
    try:
        with open(output_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"  ⚠️  Failed to parse agent output: {e}")
        return None


def allocate_ports(count: int, start_port: int = 4318) -> List[int]:
    """Pre-allocate a list of free ports for concurrent runs.
    
    Uses a simple offset scheme to avoid race conditions.
    """
    import socket
    import random
    
    # Use a random offset to avoid conflicts across multiple leaderboard runs
    base_offset = random.randint(0, 500)
    ports = []
    
    for i in range(count):
        port = start_port + base_offset + (i * 10)  # Space ports 10 apart
        # Verify port is free
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                ports.append(port)
            except OSError:
                # Port in use, try next
                for offset in range(1, 10):
                    alt_port = port + offset
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                            s2.bind(('0.0.0.0', alt_port))
                            ports.append(alt_port)
                            break
                    except OSError:
                        continue
                else:
                    ports.append(None)  # No port found
    
    return ports


def run_agentz(
    scenario_path: Path,
    scenario_name: str,
    run_id: str,
    model: str,
    model_provider: str,
    output_dir: Path,
    traces_dir: Path,
    collect_traces: bool = True,
    verbose: bool = False,
    otel_port: Optional[int] = None,
) -> Tuple[Optional[Dict], float, Dict[str, Any]]:
    """
    Run agentz on a scenario.
    
    Returns:
        Tuple of (agent_output, duration_seconds, trace_metrics)
    """
    # Build output paths
    run_output_dir = output_dir / scenario_name / run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)
    agent_output_path = run_output_dir / "agent_output.json"
    
    # Build descriptive trace filename: {model_provider}_{model}_{scenario}_{run}.jsonl
    # Sanitize model name (replace / with _)
    safe_model = model.replace("/", "_").replace("\\", "_")
    safe_provider = model_provider.replace("/", "_").replace("\\", "_")
    trace_filename = f"{safe_provider}_{safe_model}_{scenario_name}_{run_id}.jsonl"
    traces_path = traces_dir / trace_filename
    
    # If no port provided and collecting traces, disable traces
    # (port should be pre-allocated by caller for concurrent runs)
    if collect_traces and otel_port is None:
        collect_traces = False
    
    # Ensure traces directory exists
    if collect_traces:
        traces_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Build command
    cmd = [
        sys.executable, "-m", "agentz",
        "--scenario-dir", str(scenario_path),
        "--run-id", run_id,
        "--model", model,
        "--model-provider", model_provider,
        "--output-dir", str(run_output_dir), # Pass the SPECIFIC run directory
        # Add output_dir as writable root to allow sandbox to write there
        "--writable-root", str(run_output_dir.resolve()),
    ]
    
    # Agentz writes traces to: {output_dir}/traces.jsonl OR {traces_output_dir}/traces.jsonl
    # We want it in a temp location or directly to our traces folder?
    # Agentz config now expects --traces-output-dir to be the directory containing traces.jsonl
    # Let's put raw traces in the run directory first, then copy
    agentz_traces_dir = run_output_dir
    agentz_traces_path = agentz_traces_dir / "traces.jsonl"
    
    if collect_traces:
        cmd.append("--collect-traces")
        cmd.extend(["--otel-port", str(otel_port)])
        # Tell agentz to write traces.jsonl in the run directory
        cmd.extend(["--traces-output-dir", str(agentz_traces_dir)])
    
    if verbose:
        cmd.append("--verbose")
    
    # Pass current environment
    env = os.environ.copy()
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout
            cwd=Path(__file__).parent,
            env=env
        )
        
        duration = time.time() - start_time
        
        if result.returncode != 0:
            print(f"  ⚠️  Agent returned non-zero exit code: {result.returncode}")
            # Always show error output for debugging
            stderr = result.stderr.strip() if result.stderr else ""
            stdout = result.stdout.strip() if result.stdout else ""
            if stderr:
                print(f"  STDERR: {stderr[-300:]}")
            elif stdout:
                print(f"  STDOUT: {stdout[-300:]}")
        
        # Load agent output
        agent_output = load_agent_output(agent_output_path)
        
        # Parse traces for metrics and copy to descriptive filename
        trace_metrics = {}
        if collect_traces:
            # Parse from agentz's output location
            trace_metrics = parse_traces(agentz_traces_path)
            
            # Copy raw OTEL traces to descriptive filename
            if agentz_traces_path.exists():
                traces_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(agentz_traces_path, traces_path)
                if verbose:
                    print(f"  📄 Traces saved to: {traces_path}")
        
        return agent_output, duration, trace_metrics
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        print(f"  ❌ Agent timed out after 15 minutes")
        return None, duration, {}
    except Exception as e:
        duration = time.time() - start_time
        print(f"  ❌ Failed to run agent: {e}")
        return None, duration, {}


def evaluate_with_judge(
    ground_truth: Dict,
    agent_output: Dict,
    judge_model: str,
    judge_base_url: str,
    judge_api_key: str,
) -> Dict:
    """
    Use LLM-as-judge to evaluate agent output against ground truth.
    """
    evaluator = LAAJEvaluator(
        model=judge_model,
        base_url=judge_base_url,
        api_key=judge_api_key,
    )
    return evaluator.evaluate(ground_truth, agent_output)


def get_all_scenarios(snapshots_base: Path) -> List[Path]:
    """Get all scenario directories from the snapshots folder."""
    scenarios = []
    
    sre_dir = snapshots_base / "snapshots" / "sre"
    
    if not sre_dir.exists():
        print(f"⚠️  SRE snapshots directory not found: {sre_dir}")
        return scenarios
    
    for version_dir in sre_dir.iterdir():
        if version_dir.is_dir() and version_dir.name.startswith("v"):
            for uuid_dir in version_dir.iterdir():
                if uuid_dir.is_dir() and not uuid_dir.name.endswith(".zip"):
                    for scenario_dir in sorted(uuid_dir.iterdir()):
                        if scenario_dir.is_dir() and scenario_dir.name.startswith("Scenario-"):
                            scenarios.append(scenario_dir)
    
    return scenarios


def update_manifest(results_dir: Path):
    """Update manifest.json with list of all result files."""
    manifest_path = results_dir / "manifest.json"
    
    result_files = sorted([
        f.name for f in results_dir.glob("result_*.json")
        if f.name != "manifest.json"
    ])
    
    manifest = {
        "files": result_files,
        "updated": datetime.now().isoformat()
    }
    
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    
    print(f"  📋 Updated manifest with {len(result_files)} result file(s)")


# ============================================================================
# Metric Calculation
# ============================================================================

METRIC_NAMES = [
    "root_cause_entity",
    "root_cause_reasoning",
    "propagation_chain",
    "root_cause_reasoning_partial",
    "root_cause_proximity_no_fp",
    "root_cause_proximity_with_fp",
]


def calculate_metric_stats(runs: List[Dict]) -> Dict[str, Dict[str, float]]:
    """Calculate average, min, max for each metric across all runs."""
    if not runs:
        return {name: {"avg": 0, "min": 0, "max": 0} for name in METRIC_NAMES}
    
    metric_stats = {}
    for metric_name in METRIC_NAMES:
        values = [run.get("metrics", {}).get(metric_name, 0) for run in runs]
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


# ============================================================================
# Concurrent Execution
# ============================================================================

_print_lock = threading.Lock()


def run_single_iteration(
    run_idx: int,
    scenario_path: Path,
    scenario_name: str,
    ground_truth: Dict,
    model: str,
    model_provider: str,
    output_dir: Path,
    traces_dir: Path,
    judge_model: str,
    judge_base_url: str,
    judge_api_key: str,
    collect_traces: bool = True,
    otel_port: Optional[int] = None,
) -> Dict:
    """Run a single agent iteration and evaluate it."""
    run_num = run_idx + 1
    run_id = str(run_num)
    
    with _print_lock:
        port_info = f", port {otel_port}" if otel_port else ""
        print(f"    🔄 [{scenario_name}] Starting run {run_num}{port_info}...")
    
    # Run the agent
    agent_output, duration, trace_metrics = run_agentz(
        scenario_path=scenario_path,
        scenario_name=scenario_name,
        run_id=run_id,
        model=model,
        model_provider=model_provider,
        output_dir=output_dir,
        traces_dir=traces_dir,
        collect_traces=collect_traces,
        verbose=False,
        otel_port=otel_port,
    )
    
    inference_count = trace_metrics.get("inference_count", 0)
    
    if not agent_output:
        with _print_lock:
            print(f"    ❌ [{scenario_name}] Run {run_num}: No agent output ({duration:.1f}s, {inference_count} inferences)")
        return {
            "run": run_num,
            "score": 0,
            "duration_seconds": duration,
            "inference_count": inference_count,
            "trace_metrics": trace_metrics,
            "metrics": {name: 0 for name in METRIC_NAMES},
            "justification": "No agent output produced",
        }
    
    entities = agent_output.get("entities", [])
    with _print_lock:
        print(f"    📋 [{scenario_name}] Run {run_num}: {len(entities)} entities, evaluating...")
    
    # Evaluate with judge
    eval_result = evaluate_with_judge(
        ground_truth,
        agent_output,
        judge_model,
        judge_base_url,
        judge_api_key
    )
    
    score = eval_result.get("score", 0)
    metrics = eval_result.get("metrics", {})
    
    score_icon = "✅" if score == 100 else "❌"
    with _print_lock:
        print(f"    {score_icon} [{scenario_name}] Run {run_num}: Score {score}/100 ({duration:.1f}s, {inference_count} inferences)")
    
    return {
        "run": run_num,
        "score": score,
        "duration_seconds": duration,
        "inference_count": inference_count,
        "trace_metrics": trace_metrics,
        "metrics": metrics,
        "justification": eval_result.get("justification", ""),
        "error": eval_result.get("error"),
        "agent_entities": entities,
    }


def run_scenario_concurrent(
    scenario_path: Path,
    scenario_name: str,
    ground_truth: Dict,
    num_runs: int,
    completed_runs: int,
    model: str,
    model_provider: str,
    output_dir: Path,
    traces_dir: Path,
    judge_model: str,
    judge_base_url: str,
    judge_api_key: str,
    max_workers: Optional[int] = None,
    collect_traces: bool = True,
) -> List[Dict]:
    """Run multiple iterations of a scenario concurrently."""
    remaining_runs = num_runs - completed_runs
    if remaining_runs <= 0:
        return []
    
    workers = max_workers or remaining_runs
    workers = min(workers, remaining_runs)
    
    # Pre-allocate ports for all concurrent runs to avoid race conditions
    ports = []
    if collect_traces:
        ports = allocate_ports(remaining_runs)
        print(f"\n  ⚡ Running {remaining_runs} iterations concurrently (max {workers} workers)")
        print(f"     OTEL ports: {[p for p in ports if p]}")
    else:
        print(f"\n  ⚡ Running {remaining_runs} iterations concurrently (max {workers} workers)...")
        ports = [None] * remaining_runs
    
    results = []
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, run_idx in enumerate(range(completed_runs, num_runs)):
            otel_port = ports[i] if i < len(ports) else None
            future = executor.submit(
                run_single_iteration,
                run_idx,
                scenario_path,
                scenario_name,
                ground_truth,
                model,
                model_provider,
                output_dir,
                traces_dir,
                judge_model,
                judge_base_url,
                judge_api_key,
                collect_traces and otel_port is not None,
                otel_port,
            )
            futures[future] = run_idx
        
        for future in as_completed(futures):
            run_idx = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"    ❌ [{scenario_name}] Run {run_idx + 1} failed: {e}")
                results.append({
                    "run": run_idx + 1,
                    "score": 0,
                    "justification": f"Exception: {e}",
                    "error": str(e)
                })
    
    results.sort(key=lambda x: x["run"])
    return results


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate Agentz on ITBench scenarios and generate leaderboard results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with ETE provider
  python create_leaderboard.py -m aws/claude-opus-4-5 --model-provider ete

  # OpenRouter with specific model
  python create_leaderboard.py -m anthropic/claude-opus-4.5 --model-provider openrouter

  # Multiple runs with concurrency
  python create_leaderboard.py -m gpt-4o --model-provider openai --runs 5 --concurrent

  # Specific scenarios only
  python create_leaderboard.py -m o3 --model-provider openai --scenarios Scenario-1 Scenario-3

Environment Variables:
  ETE_API_KEY        API key for ETE provider
  OR_API_KEY         API key for OpenRouter
  OPENAI_API_KEY     API key for OpenAI
  OPENROUTER_API_KEY API key for judge (defaults to OR_API_KEY)
        """
    )
    
    # Agent configuration (matches agentz CLI)
    parser.add_argument("-m", "--model", required=True,
                        help="Model name for the agent (e.g., aws/claude-opus-4-5)")
    parser.add_argument("--model-provider", required=True,
                        choices=["openrouter", "openai", "azure", "ete", "custom"],
                        help="Model provider")
    
    # Judge configuration
    parser.add_argument("--judge-model", default="google/gemini-2.5-pro",
                        help="Model for LLM-as-judge (default: google/gemini-2.5-pro)")
    parser.add_argument("--judge-base-url", default="https://openrouter.ai/api/v1",
                        help="Base URL for judge API")
    parser.add_argument("--judge-api-key",
                        help="API key for judge (default: OPENROUTER_API_KEY)")
    
    # Run configuration
    parser.add_argument("--runs", type=int, default=5,
                        help="Number of runs per scenario (default: 5)")
    parser.add_argument("--scenarios", nargs="+",
                        help="Specific scenarios to run (e.g., Scenario-1 Scenario-3)")
    parser.add_argument("--scenarios-dir",
                        help="Path to scenarios directory")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for agent results (default: website/results/raw)")
    parser.add_argument("--output",
                        help="Result file path (default: website/results/result_<model>.json)")
    
    # Execution options
    parser.add_argument("--concurrent", "-c", action="store_true",
                        help="Run repetitions concurrently")
    parser.add_argument("--max-workers", type=int,
                        help="Max concurrent workers")
    parser.add_argument("--no-traces", action="store_true",
                        help="Disable OTEL trace collection")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    
    args = parser.parse_args()
    
    # Validate judge API key
    judge_api_key = (
        args.judge_api_key or
        os.environ.get("OPENROUTER_API_KEY") or
        os.environ.get("OR_API_KEY") or
        os.environ.get("OPENAI_API_KEY")
    )
    if not judge_api_key:
        print("❌ Error: Judge API key required.")
        print("   Set --judge-api-key or OPENROUTER_API_KEY environment variable.")
        sys.exit(1)
    
    project_root = Path(__file__).parent
    
    # Set up output directories
    results_dir = project_root / "website" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Agent artifacts go to results/raw/ by default
    output_dir = Path(args.output_dir) if args.output_dir else (results_dir / "raw")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Show configuration
    masked_key = f"{judge_api_key[:8]}...{judge_api_key[-4:]}" if len(judge_api_key) > 12 else "***"
    print(f"\n🔧 Configuration:")
    print(f"   Agent Model:    {args.model}")
    print(f"   Agent Provider: {args.model_provider}")
    print(f"   Judge Model:    {args.judge_model}")
    print(f"   Judge API Key:  {masked_key}")
    print(f"   Output Dir:     {output_dir}")
    print(f"   Collect Traces: {not args.no_traces}")
    print()
    
    # Find scenarios
    if args.scenarios_dir:
        scenarios_path = Path(args.scenarios_dir)
        if not scenarios_path.exists():
            print(f"❌ Error: Scenarios directory not found: {scenarios_path}")
            sys.exit(1)
        all_scenarios = sorted([
            d for d in scenarios_path.iterdir()
            if d.is_dir() and d.name.startswith("Scenario-")
        ])
    else:
        itbench_path = project_root / "ITBench-Snapshots"
        if not itbench_path.exists():
            print("❌ Error: ITBench-Snapshots not found.")
            print("   Run: git submodule update --init --recursive")
            sys.exit(1)
        all_scenarios = get_all_scenarios(itbench_path)
    
    if args.scenarios:
        scenario_filter = set(args.scenarios)
        all_scenarios = [s for s in all_scenarios if s.name in scenario_filter]
    
    if not all_scenarios:
        print("❌ Error: No scenarios found.")
        sys.exit(1)
    
    print(f"🔍 Found {len(all_scenarios)} scenarios")
    print(f"🔄 Running {args.runs} iterations per scenario")
    if args.concurrent:
        workers = args.max_workers or args.runs
        print(f"⚡ Concurrent mode: up to {workers} workers")
    print()
    
    # Model name for output file
    model_name_clean = f"{args.model_provider}_{args.model}".replace("/", "_").replace(":", "_")
    
    # Result file path
    output_path = Path(args.output) if args.output else (results_dir / f"result_{model_name_clean}.json")
    
    # Traces go in a traces subdirectory
    traces_dir = results_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize or load existing results
    results = {
        "model": args.model,
        "model_provider": args.model_provider,
        "judge_model": args.judge_model,
        "runs_per_scenario": args.runs,
        "timestamp": datetime.now().isoformat(),
        "scenarios": {},
        "summary": {}
    }
    
    if output_path.exists():
        try:
            with open(output_path, "r") as f:
                existing = json.load(f)
                print(f"🔄 Resuming from: {output_path}")
                results["scenarios"] = existing.get("scenarios", {})
        except Exception as e:
            print(f"⚠️  Failed to load existing results: {e}")
    
    total_scores = []
    total_inferences = []
    
    for scenario_path in all_scenarios:
        scenario_name = scenario_path.name
        
        # Check if already completed
        existing_scenario = results["scenarios"].get(scenario_name)
        if existing_scenario and len(existing_scenario.get("runs", [])) >= args.runs:
            print(f"\n⏭️  Skipping {scenario_name} (already completed)")
            total_scores.extend(existing_scenario.get("scores", []))
            total_inferences.extend([r.get("inference_count", 0) for r in existing_scenario.get("runs", [])])
            continue
        
        print(f"\n{'='*60}")
        print(f"📁 Scenario: {scenario_name}")
        print(f"{'='*60}")
        
        ground_truth = load_ground_truth(scenario_path)
        if not ground_truth:
            print(f"  ⏭️  Skipping (no ground truth)")
            continue
        
        # Initialize scenario results
        if existing_scenario:
            scenario_results = existing_scenario
            completed_runs = len(scenario_results.get("runs", []))
        else:
            scenario_results = {"runs": [], "scores": []}
            completed_runs = 0
        
        # Run iterations
        if args.concurrent:
            run_results = run_scenario_concurrent(
                scenario_path=scenario_path,
                scenario_name=scenario_name,
                ground_truth=ground_truth,
                num_runs=args.runs,
                completed_runs=completed_runs,
                model=args.model,
                model_provider=args.model_provider,
                output_dir=output_dir,
                traces_dir=traces_dir,
                judge_model=args.judge_model,
                judge_base_url=args.judge_base_url,
                judge_api_key=judge_api_key,
                max_workers=args.max_workers,
                collect_traces=not args.no_traces,
            )
            
            for r in run_results:
                scenario_results["runs"].append(r)
                scenario_results["scores"].append(r["score"])
        else:
            # Sequential execution - can use fixed port since only one at a time
            for run_idx in range(completed_runs, args.runs):
                print(f"\n  🔄 Run {run_idx + 1}/{args.runs}")
                
                result = run_single_iteration(
                    run_idx=run_idx,
                    scenario_path=scenario_path,
                    scenario_name=scenario_name,
                    ground_truth=ground_truth,
                    model=args.model,
                    model_provider=args.model_provider,
                    output_dir=output_dir,
                    traces_dir=traces_dir,
                    judge_model=args.judge_model,
                    judge_base_url=args.judge_base_url,
                    judge_api_key=judge_api_key,
                    collect_traces=not args.no_traces,
                    otel_port=4318 if not args.no_traces else None,
                )
                
                scenario_results["runs"].append(result)
                scenario_results["scores"].append(result["score"])
                
                # Save progress
                results["scenarios"][scenario_name] = scenario_results
                with open(output_path, "w") as f:
                    json.dump(results, f, indent=2)
        
        # Calculate scenario statistics
        scores = scenario_results["scores"]
        scenario_results["avg_score"] = sum(scores) / len(scores) if scores else 0
        scenario_results["min_score"] = min(scores) if scores else 0
        scenario_results["max_score"] = max(scores) if scores else 0
        scenario_results["metric_stats"] = calculate_metric_stats(scenario_results["runs"])
        scenario_results["duration_stats"] = calculate_duration_stats(scenario_results["runs"])
        scenario_results["inference_stats"] = calculate_inference_stats(scenario_results["runs"])
        
        results["scenarios"][scenario_name] = scenario_results
        total_scores.extend(scores)
        total_inferences.extend([r.get("inference_count", 0) for r in scenario_results["runs"]])
        
        # Save after each scenario
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        
        inf_avg = scenario_results["inference_stats"].get("avg", 0)
        dur_avg = scenario_results["duration_stats"].get("avg", 0)
        print(f"\n  📈 Summary: avg={scenario_results['avg_score']:.1f}, "
              f"inferences={inf_avg:.1f}, time={dur_avg:.1f}s")
    
    # Calculate overall statistics
    overall_metric_avgs = {}
    for metric_name in METRIC_NAMES:
        scenario_avgs = [
            s.get("metric_stats", {}).get(metric_name, {}).get("avg", 0)
            for s in results["scenarios"].values()
        ]
        overall_metric_avgs[metric_name] = sum(scenario_avgs) / len(scenario_avgs) if scenario_avgs else 0
    
    all_durations = []
    all_inferences = []
    for s in results["scenarios"].values():
        for run in s.get("runs", []):
            if run.get("duration_seconds"):
                all_durations.append(run["duration_seconds"])
            if run.get("inference_count"):
                all_inferences.append(run["inference_count"])
    
    results["summary"] = {
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
    
    # Write final results
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    update_manifest(results_dir)
    
    print(f"\n{'='*60}")
    print("📊 FINAL RESULTS")
    print(f"{'='*60}")
    print(f"  Model: {args.model} ({args.model_provider})")
    print(f"  Scenarios: {results['summary']['total_scenarios']}")
    print(f"  Total runs: {results['summary']['total_runs']}")
    print(f"  Average score: {results['summary']['overall_avg_score']:.2f}")
    print(f"  Total inferences: {results['summary']['inferences']['total']}")
    print(f"  Avg inferences/run: {results['summary']['inferences']['avg']:.1f}")
    print(f"  Total duration: {results['summary']['duration']['total']:.1f}s")
    print(f"  Avg duration/run: {results['summary']['duration']['avg']:.1f}s")
    print(f"\n  Results: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
