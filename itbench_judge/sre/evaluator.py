"""
SRE Evaluator - LLM-as-a-Judge for Root Cause Analysis.

Evaluates agent outputs against ground truth using ITBench's
6-metric evaluation rubric for SRE root cause analysis.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from asteval import Interpreter

import litellm

from .prompts import LAAJ_SYSTEM_PROMPT, EVALUATE_PROMPT_TEMPLATE


logger = logging.getLogger("itbench_judge.sre")


# Metric names used in scoring
METRIC_NAMES = [
    "root_cause_entity",
    "root_cause_reasoning",
    "propagation_chain",
    "root_cause_reasoning_partial",
    "root_cause_proximity_no_fp",
    "root_cause_proximity_with_fp",
]


@dataclass
class JudgeConfig:
    """Configuration for the LLM judge."""

    model: str
    base_url: str
    api_key: str
    provider: str = ""
    temperature: float = 0.0


@dataclass
class RunMetadata:
    """Metadata for a single agent run."""

    scenario_name: str
    agent_model: str
    agent_provider: str
    run_id: str
    duration_seconds: float = 0.0
    inference_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class RunResult:
    """Result of evaluating a single agent run."""

    metadata: RunMetadata
    scores: Dict[str, int] = field(default_factory=dict)
    justification: str = ""
    judge_model: str = ""
    judge_provider: str = ""
    evaluated_at: str = ""
    error: Optional[str] = None
    judge_raw_response: Optional[str] = None

    def __post_init__(self):
        """Set evaluation timestamp."""
        if not self.evaluated_at:
            self.evaluated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "metadata": self.metadata.to_dict(),
            "scores": self.scores,
            "justification": self.justification,
            "judge_model": self.judge_model,
            "judge_provider": self.judge_provider,
            "evaluated_at": self.evaluated_at,
            "error": self.error,
        }

    @property
    def primary_score(self) -> int:
        """Get the primary score (root_cause_entity)."""
        return self.scores.get("root_cause_entity", 0)


class SREEvaluator:
    """LLM-as-a-Judge evaluator for SRE root cause analysis."""

    def __init__(self, config: JudgeConfig):
        """
        Initialize the SRE evaluator.

        Args:
            config: JudgeConfig with model, base_url, api_key
        """
        self.config = config
        self.aeval = Interpreter()  # Safe math evaluator

        logger.info(f"SRE Evaluator initialized with model: {config.model}")

    def evaluate(
        self,
        ground_truth: Dict[str, Any],
        agent_output: Any,
    ) -> Dict[str, Any]:
        """
        Evaluate agent output against ground truth.

        Args:
            ground_truth: Ground truth data with groups and propagations
            agent_output: Agent output (Dict or raw string)

        Returns:
            Evaluation result with scores and justification
        """
        gt_for_eval = {
            "groups": ground_truth.get("groups", []),
            "propagations": ground_truth.get("propagations", []),
        }

        # Accept either Dict or raw string
        if isinstance(agent_output, dict):
            agent_output_str = json.dumps(agent_output, indent=2)
        else:
            agent_output_str = str(agent_output)

        eval_prompt = EVALUATE_PROMPT_TEMPLATE.format(
            ground_truth=json.dumps(gt_for_eval, indent=2),
            generated_response=agent_output_str,
        )

        raw_response = None

        try:
            response = litellm.completion(
                model=self.config.model,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                messages=[
                    {"role": "system", "content": LAAJ_SYSTEM_PROMPT},
                    {"role": "user", "content": eval_prompt},
                ],
                temperature=self.config.temperature,
            )

            raw_response = response.choices[0].message.content.strip()

            result = self._process_llm_response(raw_response)
            result["judge_raw_response"] = raw_response

            return result

        except json.JSONDecodeError as e:
            return {
                "score": 0,
                "justification": f"JSON parse error: {e}",
                "judge_raw_response": raw_response,
                "error": str(e),
            }
        except Exception as e:
            return {
                "score": 0,
                "justification": f"Evaluation failed: {e}",
                "error": str(e),
                "judge_raw_response": raw_response,
            }

    def _process_llm_response(self, content: str) -> Dict[str, Any]:
        """
        Process LLM response: parse JSON and evaluate calculator_tool expressions.
        """
        # Clean markdown code fences
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1].strip()

        # Parse JSON
        data = json.loads(content)

        # Handle list response
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        if not isinstance(data, dict):
            return {"score": 0, "justification": "Unexpected response format", "error": "Not a dict"}

        # Evaluate calculator_tool expressions
        pattern = re.compile(r'^calculator_tool\(expression=["\']([^"\']+)["\']\)$')

        def evaluate_expressions(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    obj[key] = evaluate_expressions(value)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    obj[i] = evaluate_expressions(item)
            elif isinstance(obj, str):
                match = pattern.match(obj)
                if match:
                    expression = match.group(1)
                    try:
                        result = self.aeval.eval(expression)
                        logger.debug(f"Evaluated '{expression}' = {result}")
                        return result
                    except Exception as e:
                        logger.warning(f"Failed to evaluate '{expression}': {e}")
                        return f"Error: {expression}"
            return obj

        evaluated_data = evaluate_expressions(data)

        # Calculate final scores
        scores = evaluated_data.get("scores", {})

        # Propagation chain score (F1 * 100)
        chain = scores.get("propagation_chain", {})
        if chain and "details" in chain:
            f1 = chain["details"].get("f1_score")
            if isinstance(f1, (int, float)):
                chain["score"] = round(f1 * 100)

        # Root cause reasoning partial
        partial = scores.get("root_cause_reasoning_partial", {})
        if partial:
            if scores.get("root_cause_reasoning", {}).get("score") == 100:
                partial["score"] = 100
            elif scores.get("root_cause_entity", {}).get("score", 0) == 0:
                calc = partial.get("calculation")
                if isinstance(calc, (int, float)):
                    partial["score"] = round(calc)
                else:
                    partial["score"] = 0
            else:
                partial["score"] = 0

        # Proximity scores - clamp to [0, 100] range
        for metric in ["root_cause_proximity_no_fp", "root_cause_proximity_with_fp"]:
            prox = scores.get(metric, {})
            if prox:
                calc = prox.get("calculation")
                if isinstance(calc, (int, float)):
                    # Clamp to valid range [0, 100]
                    prox["score"] = max(0, min(100, round(calc)))
                elif metric == "root_cause_proximity_with_fp":
                    is_on_path = prox.get("details", {}).get("is_on_path", False)
                    if not is_on_path:
                        prox["score"] = 0

        # Extract metrics - ensure all scores are clamped to [0, 100]
        def clamp_score(val: Any) -> int:
            if isinstance(val, (int, float)):
                return max(0, min(100, int(val)))
            return 0

        metrics = {
            "root_cause_entity": clamp_score(scores.get("root_cause_entity", {}).get("score", 0)),
            "root_cause_reasoning": clamp_score(scores.get("root_cause_reasoning", {}).get("score", 0)),
            "propagation_chain": clamp_score(scores.get("propagation_chain", {}).get("score", 0)),
            "root_cause_reasoning_partial": clamp_score(scores.get("root_cause_reasoning_partial", {}).get("score", 0)),
            "root_cause_proximity_no_fp": clamp_score(scores.get("root_cause_proximity_no_fp", {}).get("score", 0)),
            "root_cause_proximity_with_fp": clamp_score(scores.get("root_cause_proximity_with_fp", {}).get("score", 0)),
        }
        evaluated_data["metrics"] = metrics

        # Primary score for backward compatibility
        root_cause_score = metrics["root_cause_entity"]
        evaluated_data["score"] = root_cause_score
        evaluated_data["justification"] = scores.get("root_cause_entity", {}).get("justification", "")

        return evaluated_data


def evaluate_single_run(
    agent_output_path: Path,
    ground_truth_path: Path,
    metadata: RunMetadata,
    judge_config: JudgeConfig,
    save_judge_output: bool = True,
) -> RunResult:
    """
    Evaluate a single agent run.

    This is the main entry point for evaluating one run of an agent
    against ground truth, with full metadata tracking.

    Args:
        agent_output_path: Path to agent_output.json
        ground_truth_path: Path to ground_truth.yaml
        metadata: RunMetadata with scenario, agent, and run info
        judge_config: JudgeConfig for the LLM judge
        save_judge_output: If True, save judge_output.json next to agent_output.json

    Returns:
        RunResult with scores and metadata
    """
    # Load agent output
    agent_output = _load_agent_output(agent_output_path)
    if agent_output is None:
        result = RunResult(
            metadata=metadata,
            scores={name: 0 for name in METRIC_NAMES},
            justification="No agent output produced",
            judge_model=judge_config.model,
            judge_provider=judge_config.provider,
            error="No agent output file",
        )
        if save_judge_output:
            _save_judge_output(agent_output_path.parent / "judge_output.json", result)
        return result

    # Load ground truth
    ground_truth = _load_ground_truth(ground_truth_path)
    if ground_truth is None:
        result = RunResult(
            metadata=metadata,
            scores={name: 0 for name in METRIC_NAMES},
            justification="No ground truth file",
            judge_model=judge_config.model,
            judge_provider=judge_config.provider,
            error="No ground truth file",
        )
        if save_judge_output:
            _save_judge_output(agent_output_path.parent / "judge_output.json", result)
        return result

    # Run evaluation
    evaluator = SREEvaluator(judge_config)
    eval_result = evaluator.evaluate(ground_truth, agent_output)

    result = RunResult(
        metadata=metadata,
        scores=eval_result.get("metrics", {}),
        justification=eval_result.get("justification", ""),
        judge_model=judge_config.model,
        judge_provider=judge_config.provider,
        error=eval_result.get("error"),
        judge_raw_response=eval_result.get("judge_raw_response"),
    )

    # Save judge output to the run directory
    if save_judge_output:
        _save_judge_output(agent_output_path.parent / "judge_output.json", result)

    return result


def _save_judge_output(output_path: Path, result: RunResult) -> None:
    """Save judge output to JSON file."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        logger.debug(f"Saved judge output to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save judge output: {e}")


def _load_agent_output(output_path: Path) -> Optional[Union[Dict, str]]:
    """Load agent output - returns Dict if valid JSON, raw string otherwise."""
    if not output_path.exists():
        return None

    try:
        content = output_path.read_text().strip()
        if not content:
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Agent output is not valid JSON, passing raw text to judge")
            return content
    except Exception as e:
        logger.error(f"Failed to read agent output: {e}")
        return None


def _load_ground_truth(gt_path: Path) -> Optional[Dict]:
    """Load ground truth YAML file."""
    if not gt_path.exists():
        return None

    try:
        with open(gt_path, "r") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse ground_truth.yaml: {e}")
        return None

