"""LAAJ Agent - LLM-as-a-Judge for RCA evaluation.

This module provides a simplified implementation of the LLM-as-a-Judge
evaluation agent without LangGraph or LangChain dependencies.
Uses the OpenAI SDK directly for all LLM interactions.
"""

import json
import re
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from asteval import Interpreter

from .client import create_judge_client, get_judge_model
from .json_fixer import simple_json_repair, fix_json_string
from . import prompts

logger = logging.getLogger("itbench_evaluations.agent")


class CalculationError(Exception):
    """Raised when LLM-generated calculator expressions have syntax errors."""
    pass


EVAL_CRITERIA = [
    "ROOT_CAUSE_ENTITY",
    # ROOT_CAUSE_ENTITY_K removed - k-metrics are now computed mathematically 
    # from per-entity matches in ROOT_CAUSE_ENTITY output
    "ROOT_CAUSE_REASONING",
    "PROPAGATION_CHAIN",
    "FAULT_LOCALIZATION",
    "ROOT_CAUSE_REASONING_PARTIAL",
    "ROOT_CAUSE_PROXIMITY",
    "ROOT_CAUSE_PROXIMITY_FP",
]

# Default k values for which to compute entity@k metrics
DEFAULT_K_VALUES = [1, 2, 3, 4, 5]


def compute_entity_metrics_at_k(
    predicted_entities: List[Dict[str, Any]],
    gt_count: int,
    k: int,
) -> Dict[str, float]:
    """Compute precision, recall, and F1 for the first k predicted entities.
    
    Args:
        predicted_entities: Ordered list of predicted entities with 'matches_gt' boolean
        gt_count: Total number of ground truth entities
        k: Number of top predictions to consider
        
    Returns:
        Dict with 'precision', 'recall', and 'f1' scores
    """
    if k <= 0 or gt_count <= 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    
    top_k = predicted_entities[:k]
    tp = sum(1 for e in top_k if e.get("matches_gt", False))
    
    precision = tp / len(top_k) if len(top_k) > 0 else 0.0
    recall = tp / gt_count
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def compute_all_k_metrics(
    root_cause_entity_result: Dict[str, Any],
    k_values: List[int] = None,
) -> Dict[int, Dict[str, float]]:
    """Compute entity@k metrics for all specified k values from per-entity matches.
    
    Args:
        root_cause_entity_result: The root_cause_entity score dict containing
            'gt_entities' and 'predicted_entities' with per-entity match info
        k_values: List of k values to compute metrics for (default: [1,2,3,4,5])
        
    Returns:
        Dict mapping k value to metrics dict with precision/recall/f1
    """
    if k_values is None:
        k_values = DEFAULT_K_VALUES
    
    predicted_entities = root_cause_entity_result.get("predicted_entities", [])
    gt_entities = root_cause_entity_result.get("gt_entities", [])
    gt_count = len(gt_entities)
    
    k_metrics = {}
    for k in k_values:
        k_metrics[k] = compute_entity_metrics_at_k(predicted_entities, gt_count, k)
    
    return k_metrics


SEMANTIC_EVAL_CRITERIA = [
    "PROPAGATION_CHAIN",
    "FAULT_LOCALIZATION",
    "ROOT_CAUSE_REASONING_PARTIAL",
    "ROOT_CAUSE_PROXIMITY",
    "ROOT_CAUSE_PROXIMITY_FP",
]


@dataclass
class EvaluationConfig:
    """Configuration for evaluation runs."""
    eval_criteria: Optional[List[str]] = None
    k: int = 3  # Legacy parameter, no longer used (k-metrics computed from per-entity matches)
    max_retries: int = 5
    retry_delay_seconds: int = 70
    api_timeout_seconds: int = 300
    max_concurrent: int = 5  # Max concurrent evaluations in batch mode


class LAAJAgent:
    """LLM-as-a-Judge Agent for RCA evaluation.
    
    This agent evaluates agent outputs against ground truth using
    an LLM as the judge. It supports multiple evaluation criteria
    and uses calculator tool placeholders for mathematical calculations.
    """
    
    def __init__(self, model: Optional[str] = None):
        """Initialize the LAAJ agent.
        
        Args:
            model: Optional model name override. If not provided,
                   uses JUDGE_MODEL environment variable.
        """
        self.client = create_judge_client()
        self.model = model or get_judge_model()
        self.aeval = Interpreter()
        
        logger.info(f"LAAJ Agent initialized with model: {self.model}")
    
    def _get_eval_prompt(self, criterion: str) -> str:
        """Get the evaluation prompt for a criterion."""
        var_name = f"{criterion}_PROMPT"
        return getattr(prompts, var_name, "")
    
    def _get_eval_output_format(self, criterion: str) -> str:
        """Get the output format template for a criterion."""
        var_name = f"{criterion}_OUTPUT_FORMAT"
        return getattr(prompts, var_name, "")
    
    def _build_incident_guidance(self, incident_id: Optional[str]) -> str:
        """Build incident-specific guidance for reasoning evaluation."""
        if not incident_id:
            return ""
        
        bullet_lines_fully_correct = ""
        bullet_lines_partially_correct = ""
        
        guidance_fully_correct = prompts.INCIDENT_SPECIFIC_FULLY_CORRECT_REASONING.get(str(incident_id))
        if guidance_fully_correct:
            instruction = prompts.FULLY_CORRECT_REASONING_FEW_SHOT
            if isinstance(guidance_fully_correct, (list, tuple)):
                bullet_lines_fully_correct = instruction + "\n".join(
                    f"- {item}" for item in guidance_fully_correct if item
                )
            else:
                bullet_lines_fully_correct = instruction + f"- {guidance_fully_correct}"
        
        guidance_partially_correct = prompts.INCIDENT_SPECIFIC_PARTIALLY_CORRECT_REASONING.get(str(incident_id))
        if guidance_partially_correct:
            instruction = prompts.PARTIALLY_CORRECT_REASONING_FEW_SHOT
            if isinstance(guidance_partially_correct, (list, tuple)):
                bullet_lines_partially_correct = instruction + "\n".join(
                    f"- {item}" for item in guidance_partially_correct if item
                )
            else:
                bullet_lines_partially_correct = instruction + f"- {guidance_partially_correct}"
        
        return f"{bullet_lines_fully_correct}\n{bullet_lines_partially_correct}"
    
    def _build_system_prompt(
        self,
        selected_criteria: List[str],
        incident_id: Optional[str] = None,
        k: int = 3,
    ) -> str:
        """Build the system prompt from selected evaluation criteria."""
        eval_prompts = {}
        eval_output_formats = {}
        criterion_index = 1
        
        # Initialize ROOT_CAUSE_ENTITY_K to empty (no longer uses LLM, computed mathematically)
        eval_prompts["ROOT_CAUSE_ENTITY_K"] = ""
        eval_output_formats["ROOT_CAUSE_ENTITY_K"] = ""
        
        for criterion in EVAL_CRITERIA:
            if criterion in selected_criteria:
                # Handle special formatting for certain criteria
                if criterion == "ROOT_CAUSE_REASONING":
                    entity_correctness_steps = (
                        prompts.ENTITY_CORRECTNESS_STEPS 
                        if "ROOT_CAUSE_ENTITY" not in selected_criteria 
                        else ""
                    )
                    eval_prompts[criterion] = self._get_eval_prompt(criterion).format(
                        id=criterion_index, entity_correctness_steps=entity_correctness_steps
                    )
                elif criterion == "ROOT_CAUSE_REASONING_PARTIAL":
                    if "ROOT_CAUSE_REASONING" not in selected_criteria:
                        if "ROOT_CAUSE_ENTITY" not in selected_criteria:
                            entity_and_reasoning_steps = (
                                prompts.ENTITY_CORRECTNESS_STEPS + "\n" + 
                                prompts.REASONING_CORRECTNESS_STEPS
                            )
                        else:
                            entity_and_reasoning_steps = prompts.REASONING_CORRECTNESS_STEPS
                    else:
                        entity_and_reasoning_steps = ""
                    eval_prompts[criterion] = self._get_eval_prompt(criterion).format(
                        id=criterion_index, entity_and_reasoning_steps=entity_and_reasoning_steps
                    )
                else:
                    eval_prompts[criterion] = self._get_eval_prompt(criterion).format(
                        id=criterion_index
                    )
                eval_output_formats[criterion] = self._get_eval_output_format(criterion)
                criterion_index += 1
            else:
                eval_prompts[criterion] = ""
                eval_output_formats[criterion] = ""
        
        # Determine semantic grouping
        semantic_grouping = (
            prompts.SEMANTIC_GROUPING_PROMPT 
            if any(c in selected_criteria for c in SEMANTIC_EVAL_CRITERIA)
            else prompts.NO_SEMANTIC_GROUPING_PROMPT
        )
        
        return prompts.LAAJ_SYSTEM_PROMPT.format(
            semantic_grouping=semantic_grouping,
            root_cause_entity=eval_prompts["ROOT_CAUSE_ENTITY"],
            root_cause_entity_k=eval_prompts["ROOT_CAUSE_ENTITY_K"],
            root_cause_reasoning=eval_prompts["ROOT_CAUSE_REASONING"],
            propagation_chain=eval_prompts["PROPAGATION_CHAIN"],
            fault_localization=eval_prompts["FAULT_LOCALIZATION"],
            root_cause_reasoning_partial=eval_prompts["ROOT_CAUSE_REASONING_PARTIAL"],
            root_cause_proximity=eval_prompts["ROOT_CAUSE_PROXIMITY"],
            root_cause_proximity_fp=eval_prompts["ROOT_CAUSE_PROXIMITY_FP"],
            root_cause_entity_output_format=eval_output_formats["ROOT_CAUSE_ENTITY"],
            root_cause_entity_k_output_format=eval_output_formats["ROOT_CAUSE_ENTITY_K"],
            root_cause_reasoning_output_format=eval_output_formats["ROOT_CAUSE_REASONING"],
            propagation_chain_output_format=eval_output_formats["PROPAGATION_CHAIN"],
            fault_localization_output_format=eval_output_formats["FAULT_LOCALIZATION"],
            root_cause_reasoning_partial_output_format=eval_output_formats["ROOT_CAUSE_REASONING_PARTIAL"],
            root_cause_proximity_output_format=eval_output_formats["ROOT_CAUSE_PROXIMITY"],
            root_cause_proximity_fp_output_format=eval_output_formats["ROOT_CAUSE_PROXIMITY_FP"],
        )
    
    def _build_user_prompt(
        self,
        ground_truth: Dict[str, Any],
        agent_output: Dict[str, Any],
        incident_id: Optional[str] = None,
        selected_criteria: Optional[List[str]] = None,
    ) -> str:
        """Build the user prompt with GT and agent output."""
        incident_guidance = ""
        if selected_criteria and "ROOT_CAUSE_REASONING" in selected_criteria:
            incident_guidance = self._build_incident_guidance(incident_id)
        
        return prompts.EVALUATE_PROMPT_TEMPLATE.format(
            ground_truth=json.dumps(ground_truth, indent=2),
            generated_response=json.dumps(agent_output, indent=2),
            incident_specific_guidance=incident_guidance,
        )
    
    def _process_response(self, content: str, raise_on_calc_error: bool = True) -> Dict[str, Any]:
        """Process LLM response: parse JSON and evaluate calculator expressions.
        
        Args:
            content: Raw LLM response content
            raise_on_calc_error: If True, raise CalculationError on syntax errors in expressions.
                                 If False, return 0 for failed expressions (legacy behavior).
        
        Returns:
            Processed evaluation data with calculator expressions evaluated.
            
        Raises:
            CalculationError: If raise_on_calc_error=True and expression evaluation fails.
        """
        # Clean markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            # Try to extract JSON between code blocks
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1].strip()
        
        # Parse JSON
        data = json.loads(content)
        
        # Handle list response (expected format is a list with one item)
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        # Evaluate calculator_tool expressions
        pattern = re.compile(r'^calculator_tool\(expression=["\']([^"\']+)["\']\)$')
        calc_errors = []  # Track calculation errors for potential retry
        
        def evaluate_expressions(obj):
            if isinstance(obj, dict):
                return {k: evaluate_expressions(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [evaluate_expressions(item) for item in obj]
            elif isinstance(obj, str):
                match = pattern.match(obj)
                if match:
                    expr = match.group(1)
                    try:
                        result = self.aeval.eval(expr)
                        logger.debug(f"Evaluated '{expr}' to {result}")
                        return result
                    except Exception as e:
                        # Log the error with the expression for debugging
                        print(f"{expr}")
                        print(f"{type(e).__name__}: {e}")
                        calc_errors.append((expr, e))
                        return 0  # Return 0 for now, will raise later if needed
            return obj
        
        result = evaluate_expressions(data)
        
        # If there were calculation errors and we should raise, do so
        if calc_errors and raise_on_calc_error:
            error_details = "; ".join(f"'{expr}': {e}" for expr, e in calc_errors)
            raise CalculationError(f"Failed to evaluate {len(calc_errors)} expression(s): {error_details}")
        
        return result
    
    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        config: EvaluationConfig,
    ) -> str:
        """Call the judge LLM with retry logic."""
        for attempt in range(config.max_retries):
            try:
                response = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            temperature=0,
                        )
                    ),
                    timeout=config.api_timeout_seconds
                )
                
                content = response.choices[0].message.content
                
                # Validate JSON can be parsed
                clean_content = content
                if "```json" in clean_content:
                    clean_content = clean_content.split("```json")[1].split("```")[0].strip()
                
                # Try to parse, with repair if needed
                try:
                    json.loads(clean_content)
                except json.JSONDecodeError:
                    # Try to repair common issues (trailing/missing commas, etc.)
                    repaired = fix_json_string(clean_content)
                    json.loads(repaired)  # This will raise if still invalid
                    logger.info("JSON repaired successfully (fixed comma issues)")
                    clean_content = repaired
                
                return clean_content
                
            except asyncio.TimeoutError:
                logger.warning(
                    f"API call timed out after {config.api_timeout_seconds}s "
                    f"(attempt {attempt + 1}/{config.max_retries})"
                )
                if attempt + 1 >= config.max_retries:
                    raise
                await asyncio.sleep(30)
                
            except json.JSONDecodeError as e:
                logger.warning(
                    f"LLM generated invalid JSON "
                    f"(attempt {attempt + 1}/{config.max_retries}): {e}"
                )
                # Save problematic content to file for debugging
                if attempt + 1 >= config.max_retries:
                    debug_file = f"/tmp/judge_failed_response_{attempt}.json"
                    with open(debug_file, "w") as f:
                        f.write(f"=== ORIGINAL CONTENT ===\n{content}\n\n")
                        f.write(f"=== CLEAN CONTENT ===\n{clean_content}\n\n")
                        f.write(f"=== ERROR ===\n{e}\n")
                        f.write(f"=== AROUND ERROR (pos {e.pos}) ===\n")
                        f.write(clean_content[max(0,e.pos-100):e.pos+100])
                    logger.error(f"Saved failed response to {debug_file}")
                    raise
                await asyncio.sleep(config.retry_delay_seconds)
                
            except Exception as e:
                # Check for rate limit errors
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    logger.warning(
                        f"Rate limit hit (attempt {attempt + 1}/{config.max_retries}). "
                        f"Waiting {config.retry_delay_seconds}s."
                    )
                    if attempt + 1 >= config.max_retries:
                        raise
                    await asyncio.sleep(config.retry_delay_seconds)
                else:
                    raise
        
        raise RuntimeError("LLM call failed after all retries")
    
    async def evaluate_single(
        self,
        ground_truth: Dict[str, Any],
        agent_output: Dict[str, Any],
        incident_id: str,
        trial_id: Optional[str] = None,
        config: Optional[EvaluationConfig] = None,
    ) -> Dict[str, Any]:
        """Evaluate a single agent output against ground truth.
        
        Args:
            ground_truth: Ground truth data for the incident
            agent_output: Agent's output to evaluate
            incident_id: Incident identifier
            trial_id: Optional trial identifier
            config: Evaluation configuration
        
        Returns:
            Evaluation result with scores for each metric
        """
        config = config or EvaluationConfig()
        selected_criteria = config.eval_criteria or EVAL_CRITERIA
        
        logger.info(f"Starting evaluation for incident {incident_id}, trial {trial_id}")
        
        # Build prompts
        system_prompt = self._build_system_prompt(
            selected_criteria, incident_id, config.k
        )
        user_prompt = self._build_user_prompt(
            ground_truth, agent_output, incident_id, selected_criteria
        )
        
        # Retry loop for both LLM call AND response processing (calculator errors)
        max_calc_retries = 3
        last_error = None
        
        for calc_attempt in range(max_calc_retries):
            try:
                # Call LLM
                response = await self._call_llm(system_prompt, user_prompt, config)
                
                # Process response (may raise CalculationError on malformed expressions)
                # On last attempt, don't raise - just return 0 for bad expressions
                raise_on_calc_error = (calc_attempt < max_calc_retries - 1)
                result = self._process_response(response, raise_on_calc_error=raise_on_calc_error)
                result["incident_id"] = incident_id
                result["trial_id"] = trial_id
                
                # Compute k-metrics from per-entity matches if ROOT_CAUSE_ENTITY was evaluated
                scores = result.get("scores", {})
                root_cause_entity = scores.get("root_cause_entity", {})
                if isinstance(root_cause_entity, dict) and "predicted_entities" in root_cause_entity:
                    # Compute metrics for all k values
                    k_metrics = compute_all_k_metrics(root_cause_entity, DEFAULT_K_VALUES)
                    
                    # Add k-metrics to scores in backward-compatible format
                    # Legacy format: root_cause_entity_k (uses k=3 by default for backward compat)
                    if 3 in k_metrics:
                        scores["root_cause_entity_k"] = {
                            "calculation_precision": k_metrics[3]["precision"],
                            "calculation_recall": k_metrics[3]["recall"],
                            "calculation_f1": k_metrics[3]["f1"],
                        }
                    
                    # New format: root_cause_entity_k@{k} for each k value
                    for k, metrics in k_metrics.items():
                        scores[f"root_cause_entity_k@{k}"] = {
                            "calculation_precision": metrics["precision"],
                            "calculation_recall": metrics["recall"],
                            "calculation_f1": metrics["f1"],
                        }
                    
                    result["scores"] = scores
                    logger.info(f"Computed entity@k metrics for k={list(k_metrics.keys())}")
                
                logger.info(f"Successfully evaluated incident {incident_id}, trial {trial_id}")
                return result
                
            except CalculationError as e:
                last_error = e
                logger.warning(
                    f"Calculator expression error for {incident_id}/{trial_id} "
                    f"(attempt {calc_attempt + 1}/{max_calc_retries}): {e}"
                )
                # Will retry with a fresh LLM call
                continue
                
            except Exception as e:
                logger.error(f"Error evaluating incident {incident_id}: {e}", exc_info=True)
                return {
                    "incident_id": incident_id,
                    "trial_id": trial_id,
                    "error": str(e),
                }
        
        # If we exhausted retries due to CalculationError, return error result
        logger.error(f"Failed to evaluate {incident_id}/{trial_id} after {max_calc_retries} attempts due to calculation errors")
        return {
            "incident_id": incident_id,
            "trial_id": trial_id,
            "error": f"Calculator expression errors after {max_calc_retries} retries: {last_error}",
        }


async def evaluate_single(
    ground_truth: Dict[str, Any],
    agent_output: Dict[str, Any],
    incident_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """Convenience function for single evaluation.
    
    Args:
        ground_truth: Ground truth data for the incident
        agent_output: Agent's output to evaluate
        incident_id: Incident identifier
        **kwargs: Additional arguments passed to LAAJAgent.evaluate_single
    
    Returns:
        Evaluation result with scores
    """
    agent = LAAJAgent()
    return await agent.evaluate_single(ground_truth, agent_output, incident_id, **kwargs)


async def evaluate_batch(
    ground_truths: Dict[str, Dict[str, Any]],
    agent_outputs: Dict[str, List[Dict[str, Any]]],
    config: Optional[EvaluationConfig] = None,
) -> List[Dict[str, Any]]:
    """Evaluate multiple incidents in batch with concurrent execution.
    
    Args:
        ground_truths: Dict mapping incident_id -> ground truth dict
        agent_outputs: Dict mapping incident_id -> list of trial outputs
                       Each trial output should have:
                       - "trial": trial number (int)
                       - "output": agent output dict
        config: Evaluation configuration (includes max_concurrent setting)
    
    Returns:
        List of evaluation results for all trials
    """
    agent = LAAJAgent()
    config = config or EvaluationConfig()
    
    # Build list of all evaluation tasks
    tasks_info = []
    for incident_id, gt in ground_truths.items():
        trials = agent_outputs.get(incident_id, [])
        for trial in trials:
            trial_id = str(trial.get("trial", ""))
            output = trial.get("output", {})
            tasks_info.append({
                "incident_id": incident_id,
                "trial_id": trial_id,
                "gt": gt,
                "output": output,
            })
    
    total_tasks = len(tasks_info)
    logger.info(f"Starting batch evaluation of {total_tasks} trials across {len(ground_truths)} incidents (max_concurrent={config.max_concurrent})")
    
    # Semaphore to limit concurrent evaluations (avoid rate limiting)
    semaphore = asyncio.Semaphore(config.max_concurrent)
    
    async def evaluate_with_semaphore(task_info: Dict) -> Dict[str, Any]:
        async with semaphore:
            return await agent.evaluate_single(
                task_info["gt"],
                task_info["output"],
                task_info["incident_id"],
                trial_id=task_info["trial_id"],
                config=config,
            )
    
    # Run all evaluations concurrently (limited by semaphore)
    results = await asyncio.gather(
        *[evaluate_with_semaphore(task) for task in tasks_info],
        return_exceptions=True
    )
    
    # Process results, converting exceptions to error dicts
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            task = tasks_info[i]
            logger.error(f"Evaluation failed for {task['incident_id']}/{task['trial_id']}: {result}")
            processed_results.append({
                "incident_id": task["incident_id"],
                "trial_id": task["trial_id"],
                "error": str(result),
                "scores": {},
            })
        else:
            processed_results.append(result)
    
    logger.info(f"Batch evaluation complete: {len(processed_results)} results")
    return processed_results


