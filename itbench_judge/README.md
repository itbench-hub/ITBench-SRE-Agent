# ITBench Judge

LLM-as-a-Judge evaluator for SRE agent outputs. Compares agent diagnoses against ground truth using a language model to score multiple metrics.

## Overview

The judge module:

1. **Loads** agent output (`agent_output.json`) and ground truth (`ground_truth.yaml`)
2. **Prompts** an LLM judge with structured evaluation criteria
3. **Parses** JSON scores from the judge's response
4. **Saves** results to `judge_output.json`

## Installation

```bash
# From project root
uv sync
# or: pip install -e .
```

## Usage

### Programmatic API

```python
from pathlib import Path
from itbench_judge.sre import (
    evaluate_single_run,
    RunMetadata,
    JudgeConfig,
)

# Configure judge
judge_config = JudgeConfig(
    model="openrouter/google/gemini-2.5-pro",
    provider="openrouter",
    base_url="https://openrouter.ai/api/v1",
)

# Run evaluation
result = evaluate_single_run(
    agent_output_path=Path("./agent_output.json"),
    ground_truth_path=Path("./ground_truth.yaml"),
    metadata=RunMetadata(
        scenario_name="Scenario-3",
        agent_model="gpt-5.1",
        agent_provider="azure",
        run_id="1",
        duration_seconds=45.5,
        inference_count=12,
    ),
    judge_config=judge_config,
)

# Access results
print(f"Primary Score: {result.primary_score}/100")
print(f"All Scores: {result.scores}")
print(f"Justification: {result.justification}")
print(f"Error: {result.error}")
```

### Using the Evaluator Class

```python
from itbench_judge.sre import SREEvaluator, JudgeConfig

evaluator = SREEvaluator(JudgeConfig(
    model="openrouter/google/gemini-2.5-pro",
    provider="openrouter",
    base_url="https://openrouter.ai/api/v1",
))

# Evaluate with raw data
scores = evaluator.evaluate(
    agent_output={"entities": [...], "alerts_explained": [...]},
    ground_truth={"contributing_factors": [...], "root_cause": {...}},
)

print(scores)
# {
#     "root_cause_entity": {"score": 100, "justification": "..."},
#     "root_cause_reasoning": {"score": 80, "justification": "..."},
#     ...
# }
```

## Metrics

| Metric | Description | Scoring |
|--------|-------------|---------|
| `root_cause_entity` | Did agent identify correct root cause entity? | 0 or 100 |
| `root_cause_reasoning` | Quality of reasoning for root cause identification | 0-100 |
| `root_cause_reasoning_partial` | Partial credit for reasoning quality | 0-100 |
| `propagation_chain` | Accuracy of failure propagation chain | 0-100 |
| `root_cause_proximity_no_fp` | Distance to root cause (no false positive penalty) | 0-100 |
| `root_cause_proximity_with_fp` | Distance to root cause (with false positive penalty) | 0-100 |

### Scoring Formula

```
root_cause_proximity = (1 - (hops_away / total_path_length)) * 100
```

Where:
- `hops_away` = distance from predicted entity to actual root cause
- `total_path_length` = length of ground truth propagation path

## Data Formats

### Agent Output (`agent_output.json`)

```json
{
  "entities": [
    {
      "id": "Pod/payment-service-abc123 uid 12345-6789",
      "contributing_factor": true,
      "reasoning": "Pod crashed due to OOM. Evidence shows memory spike.",
      "evidence": "Alert: PodOOMKilled, Event: Container killed"
    }
  ],
  "alerts_explained": [
    {
      "alert": "HighErrorRate",
      "explanation": "Payment service returned 500s due to pod crash.",
      "explained": true
    }
  ]
}
```

### Ground Truth (`ground_truth.yaml`)

```yaml
contributing_factors:
  - kind: Pod
    name: payment-service-abc123
    namespace: default
    uid: 12345-6789
    is_root_cause: true
    
root_cause:
  kind: Pod
  name: payment-service-abc123
  namespace: default
  
propagation_path:
  - Pod/payment-service-abc123
  - Service/payment-service
  - Deployment/payment
```

### Judge Output (`judge_output.json`)

```json
{
  "metadata": {
    "scenario_name": "Scenario-3",
    "agent_model": "gpt-5.1",
    "run_id": "1"
  },
  "judge_raw_response": "...",
  "scores": {
    "root_cause_entity": {
      "score": 100,
      "justification": "Agent correctly identified..."
    },
    "root_cause_reasoning": {
      "score": 80,
      "justification": "Good reasoning but missed..."
    }
  },
  "primary_score": 100,
  "justification": "Agent correctly identified...",
  "error": null
}
```

## Configuration

### JudgeConfig

```python
from itbench_judge.sre import JudgeConfig

config = JudgeConfig(
    model="openrouter/google/gemini-2.5-pro",  # Judge model
    provider="openrouter",                       # Provider key
    base_url="https://openrouter.ai/api/v1",    # API endpoint
)

# API key is read from environment:
# - OR_API_KEY / OPENROUTER_API_KEY for OpenRouter
# - OPENAI_API_KEY for OpenAI
# - ETE_API_KEY for ETE
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OR_API_KEY` | OpenRouter API key |
| `OPENROUTER_API_KEY` | Alternative OpenRouter key |
| `OPENAI_API_KEY` | OpenAI API key |
| `ETE_API_KEY` | ETE LiteLLM Proxy key |

## Module Structure

```
itbench_judge/
├── __init__.py          # Public exports
└── sre/
    ├── __init__.py      # SRE-specific exports
    ├── evaluator.py     # Evaluation logic & SREEvaluator class
    └── prompts.py       # Judge prompt templates
```

### Public API

```python
from itbench_judge.sre import (
    # Functions
    evaluate_single_run,
    
    # Classes
    SREEvaluator,
    JudgeConfig,
    RunMetadata,
    RunResult,
    
    # Constants
    METRIC_NAMES,
)
```

## Error Handling

The judge handles errors gracefully:

```python
result = evaluate_single_run(...)

if result.error:
    print(f"Evaluation failed: {result.error}")
    # Scores will be 0 for all metrics
else:
    print(f"Score: {result.primary_score}")
```

Common errors:
- **JSON parse error**: Judge response wasn't valid JSON
- **API error**: Model API returned an error
- **Missing fields**: Agent output missing required fields

## Integration with Leaderboard

The leaderboard module calls the judge automatically:

```python
# In itbench_leaderboard/cli.py
from itbench_judge.sre import evaluate_single_run

result = evaluate_single_run(
    agent_output_path=workspace / "agent_output.json",
    ground_truth_path=scenario / "ground_truth.yaml",
    metadata=metadata,
    judge_config=judge_config,
)
# result.scores saved to judge_output.json
```

## See Also

- [Main README](../README.md) - Project overview
- [Leaderboard](../itbench_leaderboard/README.md) - Orchestration
- [Zero](../zero/zero-config/README.md) - Agent runner


