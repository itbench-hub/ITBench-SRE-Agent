#!/usr/bin/env python3
"""
Create Leaderboard - Evaluate SRE Support Agent on ITBench scenarios.

This script runs the SRE agent on all ITBench scenarios, evaluates the results
using an LLM-as-judge, and generates a leaderboard result file.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from evaluation import LAAJEvaluator


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


def parse_agent_output(output: str) -> Optional[Dict]:
    """Extract JSON entities from agent output."""
    # Try to find JSON block in various formats
    json_patterns = [
        r"```json\s*([\s\S]*?)\s*```",  # ```json ... ```
        r"```\s*([\s\S]*?)\s*```",       # ``` ... ```
        r"\{[\s\S]*\"entities\"[\s\S]*\}", # Raw JSON with entities
    ]
    
    for pattern in json_patterns:
        matches = re.findall(pattern, output, re.IGNORECASE)
        for match in matches:
            try:
                # Clean up the match
                json_str = match.strip() if isinstance(match, str) else match
                if not json_str.startswith("{"):
                    continue
                parsed = json.loads(json_str)
                if "entities" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue
    
    # Last resort: try to find any JSON object with entities
    try:
        # Find the last occurrence of entities JSON
        start = output.rfind('{"entities"')
        if start == -1:
            start = output.rfind("{'entities'")
        if start != -1:
            # Find matching closing brace
            depth = 0
            for i, char in enumerate(output[start:]):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        json_str = output[start:start + i + 1]
                        return json.loads(json_str.replace("'", '"'))
    except (json.JSONDecodeError, ValueError):
        pass
    
    return None


class ScrollingOutput:
    """Manages a scrolling output window in the terminal."""
    
    def __init__(self, max_lines: int = 20):
        self.max_lines = max_lines
        self.lines: List[str] = []
        self.full_output: List[str] = []
    
    def add_line(self, line: str):
        """Add a line and refresh the display."""
        self.full_output.append(line)
        self.lines.append(line)
        if len(self.lines) > self.max_lines:
            self.lines.pop(0)
        self._refresh()
    
    def _refresh(self):
        """Refresh the scrolling window display."""
        # Move cursor up and clear lines
        if len(self.lines) > 1:
            sys.stdout.write(f"\033[{min(len(self.lines), self.max_lines)}A")  # Move up
        
        # Print current window
        for i, line in enumerate(self.lines):
            # Truncate long lines
            display_line = line[:100] + "..." if len(line) > 100 else line
            sys.stdout.write(f"\033[K{display_line}\n")  # Clear line and print
        
        sys.stdout.flush()
    
    def get_full_output(self) -> str:
        """Get the complete captured output."""
        return "\n".join(self.full_output)
    
    def clear(self):
        """Clear the scrolling window."""
        for _ in range(len(self.lines)):
            sys.stdout.write("\033[A\033[K")  # Move up and clear
        sys.stdout.flush()
        self.lines = []


def run_agent(scenario_path: Path, config_path: Optional[str] = None, show_output: bool = True) -> str:
    """Run the SRE agent on a scenario with live streaming output."""
    cmd = [
        sys.executable, "-m", "sre_support_agent",
        "--dir", str(scenario_path),
        "Diagnose the incident and identify the root cause."
    ]
    
    if config_path:
        cmd.extend(["--config", config_path])
    
    try:
        if show_output:
            # Use Popen for streaming output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=Path(__file__).parent
            )
            
            scroller = ScrollingOutput(max_lines=15)
            print()  # Initial newline for scrolling space
            for _ in range(15):
                print()  # Create space for scrolling window
            
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        scroller.add_line(line.rstrip())
                
                process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                scroller.clear()
                return "ERROR: Agent timed out after 10 minutes"
            
            full_output = scroller.get_full_output()
            
            # Clear scrolling window and show final diagnosis
            scroller.clear()
            
            # Extract and display final diagnosis
            diagnosis = extract_final_diagnosis(full_output)
            if diagnosis:
                print("\n    ┌─ AGENT DIAGNOSIS ─────────────────────────────────────")
                for line in diagnosis.split('\n')[:20]:  # Show up to 20 lines
                    print(f"    │ {line}")
                if diagnosis.count('\n') > 20:
                    print(f"    │ ... [{diagnosis.count(chr(10)) - 20} more lines]")
                print("    └──────────────────────────────────────────────────────")
            
            return full_output
        else:
            # Silent mode
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=Path(__file__).parent
            )
            return result.stdout + result.stderr
            
    except subprocess.TimeoutExpired:
        return "ERROR: Agent timed out after 10 minutes"
    except Exception as e:
        return f"ERROR: Failed to run agent: {e}"


def extract_final_diagnosis(output: str) -> Optional[str]:
    """Extract the final diagnosis section from agent output."""
    # Look for FINAL DIAGNOSIS or DIAGNOSIS sections
    patterns = [
        r"FINAL DIAGNOSIS:?\s*={0,60}\s*([\s\S]*?)(?:={60}|$)",
        r"DIAGNOSIS.*?:?\s*={0,60}\s*([\s\S]*?)(?:={60}|$)",
        r'```json\s*({"entities"[\s\S]*?})\s*```',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # Fallback: find any entities JSON
    entities_match = re.search(r'(\{"entities"[\s\S]*?\})\s*$', output)
    if entities_match:
        return entities_match.group(1)
    
    return None


def evaluate_with_judge(
    ground_truth: Dict,
    agent_output: Dict,
    judge_model: str,
    judge_base_url: str,
    judge_api_key: str,
) -> Dict:
    """
    Use LLM-as-judge to evaluate agent output against ground truth.
    
    Uses the full 7-metric ITBench evaluation:
    1. Root Cause Entity Identification
    2. Root Cause Reasoning Accuracy
    3. Fault Propagation Chain Accuracy (F1)
    4. Fault Localization Component Identification
    5. Root Cause Reasoning Partial
    6. Root Cause Proximity (No FP)
    7. Root Cause Proximity (With FP)
    
    Args:
        ground_truth: Ground truth data with groups and propagations
        agent_output: Agent output with entities
        judge_model: Model name for the judge
        judge_base_url: API base URL
        judge_api_key: API key
        
    Returns:
        Evaluation result with scores and justifications
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
    
    # Navigate to the actual scenarios directory
    # Structure: ITBench-Snapshots/snapshots/sre/v0.1-.../uuid/Scenario-*/
    sre_dir = snapshots_base / "snapshots" / "sre"
    
    if not sre_dir.exists():
        print(f"⚠️  SRE snapshots directory not found: {sre_dir}")
        return scenarios
    
    # Find version directories
    for version_dir in sre_dir.iterdir():
        if version_dir.is_dir() and version_dir.name.startswith("v"):
            # Find UUID directories
            for uuid_dir in version_dir.iterdir():
                if uuid_dir.is_dir() and not uuid_dir.name.endswith(".zip"):
                    # Find Scenario directories
                    for scenario_dir in sorted(uuid_dir.iterdir()):
                        if scenario_dir.is_dir() and scenario_dir.name.startswith("Scenario-"):
                            scenarios.append(scenario_dir)
    
    return scenarios


def update_manifest(results_dir: Path):
    """Update manifest.json with list of all result files."""
    manifest_path = results_dir / "manifest.json"
    
    # Find all result JSON files
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


def create_temp_config(
    base_config_path: Optional[str],
    model_name: Optional[str],
    base_url: Optional[str],
    api_key: Optional[str]
) -> str:
    """Create a temporary config file with overrides."""
    import tempfile
    import toml
    
    # Load base config or create default
    if base_config_path and Path(base_config_path).exists():
        with open(base_config_path, "r") as f:
            config = toml.load(f)
    else:
        config = {
            "model_name": "openrouter/anthropic/claude-sonnet-4",
            "recursion_limit": 100,
            "llm_config": {
                "api_key": "",
                "base_url": "https://openrouter.ai/api/v1"
            },
            "file_tools": {"enabled": True, "base_dir": "."},
            "search_tools": {"enabled": True},
            "system_tools": {"enabled": True},
            "blacklist": {"patterns": ["ground_truth*.yaml", "*.secret", "*.key", ".env*"]}
        }
    
    # Apply overrides
    if model_name:
        config["model_name"] = model_name
    if base_url:
        config["llm_config"]["base_url"] = base_url
    if api_key:
        config["llm_config"]["api_key"] = api_key
    
    # Write to temp file
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False)
    toml.dump(config, temp_file)
    temp_file.close()
    
    return temp_file.name


# ============================================================================
# Main Execution
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate SRE Support Agent on ITBench scenarios and generate leaderboard results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_leaderboard.py
  python create_leaderboard.py --model_name openrouter/anthropic/claude-sonnet-4
  python create_leaderboard.py --runs 3 --judge_model google/gemini-2.5-pro
        """
    )
    
    # Agent configuration
    parser.add_argument("--model_name", help="Model name for the SRE agent (overrides config)")
    parser.add_argument("--base_url", help="Base URL for the SRE agent API (overrides config)")
    parser.add_argument("--api_key", help="API key for the SRE agent (overrides config)")
    parser.add_argument("--config", help="Path to base config file (default: agent.toml)")
    
    # Judge configuration
    parser.add_argument("--judge_model", default="google/gemini-2.5-pro",
                        help="Model for LLM-as-judge evaluation (default: google/gemini-2.5-pro)")
    parser.add_argument("--judge_base_url", default="https://openrouter.ai/api/v1",
                        help="Base URL for judge model API")
    parser.add_argument("--judge_api_key", help="API key for judge model")
    
    # Run configuration
    parser.add_argument("--runs", type=int, default=5,
                        help="Number of runs per scenario to capture variability (default: 5)")
    parser.add_argument("--scenarios", nargs="+",
                        help="Specific scenarios to run (e.g., Scenario-3 Scenario-16)")
    parser.add_argument("--scenarios-dir",
                        help="Path to directory containing Scenario-* folders (auto-detected if not provided)")
    parser.add_argument("--output", help="Output file path (default: website/results/result_<model>.json)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress live agent output (only show summary)")
    
    args = parser.parse_args()
    
    # Validate judge API key
    judge_api_key = args.judge_api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not judge_api_key:
        print("❌ Error: Judge API key required. Set --judge_api_key or OPENROUTER_API_KEY environment variable.")
        sys.exit(1)
    
    # Debug: Show judge configuration
    masked_key = f"{judge_api_key[:8]}...{judge_api_key[-4:]}" if len(judge_api_key) > 12 else "***"
    print(f"\n🔧 Judge Configuration (using litellm):")
    print(f"   Model:    {args.judge_model}")
    print(f"   Base URL: {args.judge_base_url}")
    print(f"   API Key:  {masked_key}")
    print()
    
    # Find scenarios
    if args.scenarios_dir:
        # Use provided directory - find all Scenario-* subdirs
        scenarios_path = Path(args.scenarios_dir)
        if not scenarios_path.exists():
            print(f"❌ Error: Scenarios directory not found: {scenarios_path}")
            sys.exit(1)
        all_scenarios = sorted([
            d for d in scenarios_path.iterdir() 
            if d.is_dir() and d.name.startswith("Scenario-")
        ])
        print(f"📂 Using scenarios from: {scenarios_path}")
    else:
        # Auto-detect from ITBench-Snapshots submodule
        project_root = Path(__file__).parent
        itbench_path = project_root / "ITBench-Snapshots"
        
        if not itbench_path.exists():
            print("❌ Error: ITBench-Snapshots submodule not found.")
            print("   Either run: git submodule update --init --recursive")
            print("   Or specify: --scenarios-dir /path/to/scenarios")
            sys.exit(1)
        
        all_scenarios = get_all_scenarios(itbench_path)
    
    if args.scenarios:
        # Filter to specific scenarios
        scenario_filter = set(args.scenarios)
        all_scenarios = [s for s in all_scenarios if s.name in scenario_filter]
    
    if not all_scenarios:
        print("❌ Error: No scenarios found to evaluate.")
        sys.exit(1)
    
    print(f"🔍 Found {len(all_scenarios)} scenarios to evaluate")
    print(f"🔄 Running {args.runs} iterations per scenario")
    print()
    
    # Debug: Show agent configuration
    agent_api_key = args.api_key or "(from config)"
    if args.api_key and len(args.api_key) > 12:
        masked_agent_key = f"{args.api_key[:8]}...{args.api_key[-4:]}"
    else:
        masked_agent_key = agent_api_key
    print(f"🤖 Agent Configuration:")
    print(f"   Model:    {args.model_name or '(from config)'}")
    print(f"   Base URL: {args.base_url or '(from config)'}")
    print(f"   API Key:  {masked_agent_key}")
    print()
    
    # Create temp config with overrides
    temp_config_path = None
    if args.model_name or args.base_url or args.api_key:
        temp_config_path = create_temp_config(
            args.config or "agent.toml",
            args.model_name,
            args.base_url,
            args.api_key
        )
    
    # Determine model name for output file
    model_name_clean = (args.model_name or "default").replace("/", "_").replace(":", "_")
    
    # Results storage
    results = {
        "model_name": args.model_name or "default",
        "judge_model": args.judge_model,
        "runs_per_scenario": args.runs,
        "timestamp": datetime.now().isoformat(),
        "scenarios": {},
        "summary": {}
    }
    
    total_scores = []
    
    for scenario_path in all_scenarios:
        scenario_name = scenario_path.name
        print(f"\n{'='*60}")
        print(f"📁 Scenario: {scenario_name}")
        print(f"{'='*60}")
        
        ground_truth = load_ground_truth(scenario_path)
        if not ground_truth:
            print(f"  ⏭️  Skipping (no ground truth)")
            continue
        
        scenario_results = {
            "runs": [],
            "scores": [],
            "avg_score": 0,
            "min_score": 0,
            "max_score": 0
        }
        
        for run_idx in range(args.runs):
            print(f"\n  ╔══════════════════════════════════════════════════════════")
            print(f"  ║ 🔄 Run {run_idx + 1}/{args.runs} - {scenario_name}")
            print(f"  ╚══════════════════════════════════════════════════════════")
            
            # Run the agent with live output
            if not args.quiet:
                print(f"    ▶️  Starting agent (live output below)...")
            else:
                print(f"    ▶️  Running agent (quiet mode)...", end="", flush=True)
            
            agent_output_raw = run_agent(
                scenario_path,
                config_path=temp_config_path or args.config,
                show_output=not args.quiet
            )
            
            if args.quiet:
                print(" done.")
            
            # Parse agent output
            agent_output = parse_agent_output(agent_output_raw)
            
            if not agent_output:
                print(f"\n    ❌ Failed to parse agent output")
                print(f"    💡 Last 500 chars of output:")
                print(f"       {agent_output_raw[-500:]}")
                run_result = {
                    "run": run_idx + 1,
                    "score": 0,
                    "justification": "Failed to parse agent output",
                    "agent_output_raw": agent_output_raw[-2000:]  # Last 2000 chars for debugging
                }
            else:
                # Show parsed entities
                entities = agent_output.get("entities", [])
                print(f"\n    📋 Parsed {len(entities)} entities from agent output")
                for ent in entities[:5]:  # Show first 5
                    cf = "✓" if ent.get("contributing_factor") else "○"
                    print(f"       {cf} {ent.get('id', 'unknown')[:50]}")
                if len(entities) > 5:
                    print(f"       ... and {len(entities) - 5} more")
                
                print(f"\n    ⚖️  Sending to judge ({args.judge_model})...")
                eval_result = evaluate_with_judge(
                    ground_truth,
                    agent_output,
                    args.judge_model,
                    args.judge_base_url,
                    judge_api_key
                )
                
                score = eval_result.get("score", 0)
                justification = eval_result.get("justification", "No justification provided")
                error = eval_result.get("error")
                judge_raw = eval_result.get("judge_raw_response")
                
                # Display score with emphasis - NO TRUNCATION
                score_icon = "✅" if score == 100 else "❌"
                print(f"\n    ┌────────────────────────────────────────────────────────────")
                print(f"    │ {score_icon} SCORE: {score}/100")
                print(f"    │")
                print(f"    │ 📝 Justification:")
                # Print full justification, wrapped
                for line in justification.split('\n'):
                    print(f"    │    {line}")
                if error:
                    print(f"    │")
                    print(f"    │ ⚠️  Error:")
                    print(f"    │    {error}")
                print(f"    └────────────────────────────────────────────────────────────")
                
                run_result = {
                    "run": run_idx + 1,
                    "score": score,
                    "justification": justification,
                    "error": error,
                    "judge_raw_response": judge_raw,
                    "agent_entities": agent_output.get("entities", [])
                }
            
            scenario_results["runs"].append(run_result)
            scenario_results["scores"].append(run_result["score"])
        
        # Calculate scenario statistics
        scores = scenario_results["scores"]
        scenario_results["avg_score"] = sum(scores) / len(scores) if scores else 0
        scenario_results["min_score"] = min(scores) if scores else 0
        scenario_results["max_score"] = max(scores) if scores else 0
        
        results["scenarios"][scenario_name] = scenario_results
        total_scores.extend(scores)
        
        print(f"\n  📈 Scenario Summary: avg={scenario_results['avg_score']:.1f}, "
              f"min={scenario_results['min_score']}, max={scenario_results['max_score']}")
    
    # Calculate overall summary
    results["summary"] = {
        "total_scenarios": len(results["scenarios"]),
        "total_runs": len(total_scores),
        "overall_avg_score": sum(total_scores) / len(total_scores) if total_scores else 0,
        "overall_min_score": min(total_scores) if total_scores else 0,
        "overall_max_score": max(total_scores) if total_scores else 0,
        "scenarios_with_perfect_score": sum(1 for s in results["scenarios"].values() if s["max_score"] == 100),
        "scenarios_with_any_success": sum(1 for s in results["scenarios"].values() if s["max_score"] > 0)
    }
    
    # Clean up temp config
    if temp_config_path:
        os.unlink(temp_config_path)
    
    # Ensure output directory exists
    output_dir = project_root / "website" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write results
    output_path = args.output or (output_dir / f"result_{model_name_clean}.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    # Update manifest.json with all result files
    update_manifest(output_dir)
    
    print(f"\n{'='*60}")
    print("📊 FINAL RESULTS")
    print(f"{'='*60}")
    print(f"  Model: {results['model_name']}")
    print(f"  Scenarios evaluated: {results['summary']['total_scenarios']}")
    print(f"  Total runs: {results['summary']['total_runs']}")
    print(f"  Overall average score: {results['summary']['overall_avg_score']:.2f}")
    print(f"  Scenarios with any success: {results['summary']['scenarios_with_any_success']}")
    print(f"  Scenarios with perfect score: {results['summary']['scenarios_with_perfect_score']}")
    print(f"\n  Results saved to: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

