"""
LAAJ (LLM-as-a-Judge) Evaluator for RCA outputs.

This module provides evaluation capabilities using an LLM-based judge
to score root cause analysis performance against ground truth.

Evaluates 7 metrics from ITBench:
1. Root Cause Entity Identification (0 or 100)
2. Root Cause Reasoning Accuracy (0 or 100)
3. Fault Propagation Chain Accuracy (F1 score * 100)
4. Fault Localization Component Identification (0 or 100)
5. Root Cause Reasoning Partial (0-100)
6. Root Cause Proximity No FP (0-100)
7. Root Cause Proximity With FP (0-100)
"""

import json
import re
import logging
from typing import Any, Dict, List, Optional
from asteval import Interpreter

import litellm

from .prompts import LAAJ_SYSTEM_PROMPT, EVALUATE_PROMPT_TEMPLATE

# Set up logging
logger = logging.getLogger("LAAJ")


class LAAJEvaluator:
    """LLM-as-a-Judge evaluator for RCA outputs using ITBench 7-metric evaluation."""
    
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        temperature: float = 0.0,
    ):
        """
        Initialize the LAAJ evaluator.
        
        Args:
            model: Model name for litellm
            base_url: API base URL
            api_key: API key
            temperature: LLM temperature (0.0 for deterministic)
        """
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        
        # Safe math evaluator for calculator_tool expressions
        self.aeval = Interpreter()
        
        logger.info(f"LAAJ Evaluator initialized with model: {model}")
    
    def evaluate(
        self,
        ground_truth: Dict[str, Any],
        agent_output: Any,
    ) -> Dict[str, Any]:
        """
        Evaluate agent output against ground truth using ITBench 7-metric evaluation.
        
        Args:
            ground_truth: Ground truth data with groups and propagations
            agent_output: Agent output - can be Dict or raw string (LLM judge handles both)
            
        Returns:
            Evaluation result with all 7 metric scores and justifications
        """
        gt_for_eval = {
            "groups": ground_truth.get("groups", []),
            "propagations": ground_truth.get("propagations", [])
        }
        
        # Accept either Dict or raw string - LLM judge can understand both
        if isinstance(agent_output, dict):
            agent_output_str = json.dumps(agent_output, indent=2)
        else:
            agent_output_str = str(agent_output)
        
        eval_prompt = EVALUATE_PROMPT_TEMPLATE.format(
            ground_truth=json.dumps(gt_for_eval, indent=2),
            generated_response=agent_output_str
        )
        
        raw_response = None
        
        try:
            response = litellm.completion(
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                messages=[
                    {"role": "system", "content": LAAJ_SYSTEM_PROMPT},
                    {"role": "user", "content": eval_prompt}
                ],
                temperature=self.temperature,
            )
            
            raw_response = response.choices[0].message.content.strip()
            
            # Process the response through deterministic calculation
            result = self._process_llm_response(raw_response)
            result["judge_raw_response"] = raw_response
            
            return result
            
        except json.JSONDecodeError as e:
            return {
                "score": 0,
                "justification": f"JSON parse error: {e}",
                "judge_raw_response": raw_response,
                "error": str(e)
            }
        except Exception as e:
            return {
                "score": 0,
                "justification": f"Evaluation failed: {e}",
                "error": str(e),
                "judge_raw_response": raw_response
            }
    
    def _process_llm_response(self, content: str) -> Dict[str, Any]:
        """
        Process LLM response: parse JSON and evaluate calculator_tool expressions.
        
        Args:
            content: Raw LLM response content
            
        Returns:
            Processed evaluation result with calculated scores
        """
        # Clean the string to remove markdown code fences
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1].strip()
        
        # Parse JSON
        data = json.loads(content)
        
        # Handle both list and dict responses
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        
        if not isinstance(data, dict):
            return {"score": 0, "justification": "Unexpected response format", "error": "Not a dict"}
        
        # Evaluate calculator_tool expressions
        pattern = re.compile(r'^calculator_tool\(expression=["\']([^"\']+)["\']\)$')
        
        def evaluate_expressions(obj):
            """Recursively find and evaluate calculator_tool expressions."""
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
        
        # Calculate final scores from evaluated expressions
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
        
        # Proximity scores
        for metric in ["root_cause_proximity_no_fp", "root_cause_proximity_with_fp"]:
            prox = scores.get(metric, {})
            if prox:
                calc = prox.get("calculation")
                if isinstance(calc, (int, float)):
                    prox["score"] = round(calc)
                elif metric == "root_cause_proximity_with_fp":
                    is_on_path = prox.get("details", {}).get("is_on_path", False)
                    if not is_on_path:
                        prox["score"] = 0
        
        # Extract 6 metric scores into a structured format (excluding fault_localization)
        metrics = {
            "root_cause_entity": scores.get("root_cause_entity", {}).get("score", 0),
            "root_cause_reasoning": scores.get("root_cause_reasoning", {}).get("score", 0),
            "propagation_chain": scores.get("propagation_chain", {}).get("score", 0),
            "root_cause_reasoning_partial": scores.get("root_cause_reasoning_partial", {}).get("score", 0),
            "root_cause_proximity_no_fp": scores.get("root_cause_proximity_no_fp", {}).get("score", 0),
            "root_cause_proximity_with_fp": scores.get("root_cause_proximity_with_fp", {}).get("score", 0),
        }
        evaluated_data["metrics"] = metrics
        
        # Primary score for backward compatibility (root_cause_entity)
        root_cause_score = metrics["root_cause_entity"]
        evaluated_data["score"] = root_cause_score
        evaluated_data["justification"] = scores.get("root_cause_entity", {}).get("justification", "")
        
        return evaluated_data


def evaluate_agent_output(
    ground_truth: Dict[str, Any],
    agent_output: Dict[str, Any],
    model: str,
    base_url: str,
    api_key: str,
) -> Dict[str, Any]:
    """
    Convenience function to evaluate agent output using ITBench 7-metric evaluation.
    
    Args:
        ground_truth: Ground truth data with groups and propagations
        agent_output: Agent output with entities
        model: Model name
        base_url: API base URL
        api_key: API key
        
    Returns:
        Evaluation result with all metric scores
    """
    evaluator = LAAJEvaluator(
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    return evaluator.evaluate(ground_truth, agent_output)

