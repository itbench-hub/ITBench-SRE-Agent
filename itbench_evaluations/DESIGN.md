# ITBench Evaluations - Design Document

## Overview

`itbench_evaluations` is a standalone evaluation library for assessing Root Cause Analysis (RCA) agent outputs using an LLM-as-a-Judge (LAAJ) approach. It provides the core evaluation logic, metrics computation, and score filtering that the leaderboard system uses.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           itbench_leaderboard                               │
│  (Orchestration: runs agents, manages experiments, aggregates results)      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ uses
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           itbench_evaluations                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  ┌───────────────┐  │
│  │   agent.py  │  │  loader.py   │  │ namespace_     │  │ aggregator.py │  │
│  │  (LAAJAgent)│  │  (I/O utils) │  │ filter.py      │  │ (statistics)  │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  └───────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         prompts/                                     │   │
│  │   (LLM prompt templates for each evaluation criterion)              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

### `agent.py` - LLM-as-a-Judge Evaluation

**Primary responsibility:** Execute LLM-based evaluation of agent outputs against ground truth.

- `LAAJAgent`: Main evaluation class that orchestrates LLM calls
- `evaluate_single()`: Evaluate a single agent output
- `evaluate_batch()`: Batch evaluation of multiple outputs
- `compute_entity_metrics_at_k()`: Calculate precision/recall/F1 for top-k predictions
- `compute_all_k_metrics()`: Compute @k metrics for k=1,2,3,4,5

**Key constants:**
- `EVAL_CRITERIA`: List of evaluation criteria (ROOT_CAUSE_ENTITY, ROOT_CAUSE_REASONING, etc.)
- `DEFAULT_K_VALUES`: [1, 2, 3, 4, 5] for entity@k metrics

### `loader.py` - Data Loading

**Primary responsibility:** Load ground truth and agent outputs from various formats.

- `load_ground_truth()`: Load GT from JSON/YAML files or directories
- `load_agent_outputs()`: Load agent outputs from trial directories
- `canonicalize_scenario_id()`: Normalize scenario IDs (e.g., "Scenario-1" → "1")

**Supported formats:**
- JSON arrays: `[{"id": "1", "groups": [...]}]`
- Single JSON/YAML files
- Directory of scenario subdirectories with `ground_truth.yaml`

### `namespace_filter.py` - Post-Evaluation Filtering

**Primary responsibility:** Filter out infrastructure entities from evaluation metrics.

This module allows recalculating entity metrics without re-running the LLM judge. It operates on the per-entity match data stored in `judge_output.json`.

**Key functions:**
- `filter_predicted_entities()`: Remove entities from excluded namespaces
- `recalculate_entity_metrics()`: Recompute precision/recall/F1 after filtering
- `apply_namespace_filter_to_scores()`: Full filtering + recalculation pipeline
- `get_filtering_summary()`: Debug utility showing what was filtered

**Default excluded namespaces:**
```python
DEFAULT_EXCLUDED_NAMESPACES = {
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
```

### `aggregator.py` - Statistics

**Primary responsibility:** Calculate aggregate statistics across multiple evaluations.

- `calculate_statistics()`: Compute mean, stderr, pass@1 per incident and overall

### `prompts/` - LLM Prompt Templates

**Primary responsibility:** Define evaluation criteria and output formats.

Each file defines prompts for one evaluation criterion:
- `entity_correctness.py`: ROOT_CAUSE_ENTITY (precision/recall/F1)
- `entity_correctness_k.py`: Entity@k metrics
- `reasoning_correctness.py`: ROOT_CAUSE_REASONING
- `propagation_chain.py`: PROPAGATION_CHAIN
- `fault_localization.py`: FAULT_LOCALIZATION
- `reasoning_partial.py`: ROOT_CAUSE_REASONING_PARTIAL
- `proximity.py` / `proximity_fp.py`: ROOT_CAUSE_PROXIMITY variants

### `client.py` - LLM Client

**Primary responsibility:** Create and configure the judge LLM client.

- `create_judge_client()`: Factory for OpenAI-compatible clients
- `get_judge_model()`: Get the configured judge model name

### `json_fixer.py` - JSON Repair

**Primary responsibility:** Repair malformed JSON from agent outputs.

- `simple_json_repair()`: Basic JSON fixing (quotes, brackets)
- `fix_json_string()`: More aggressive JSON repair

## Data Flow

### 1. Evaluation Flow (Fresh Judging)

```
Agent Output (JSON) ──┐
                      ├──▶ LAAJAgent.evaluate() ──▶ eval_result
Ground Truth (YAML) ──┘         │
                                │
                                ▼
                    ┌──────────────────────┐
                    │ eval_result contains:│
                    │ - scores (nested)    │
                    │ - justification      │
                    │ - per-entity matches │
                    └──────────────────────┘
                                │
                                ▼
                    apply_namespace_filter_to_scores()
                                │
                                ▼
                    ┌──────────────────────┐
                    │ flat_scores (filtered)│
                    │ - root_cause_entity_f1│
                    │ - root_cause_entity_* │
                    └──────────────────────┘
```

### 2. Re-Aggregation Flow (No LLM Calls)

```
judge_output.json ──▶ load_judge_output() ──▶ payload
                                │
                                ▼
                    apply_score_filters()
                                │
                    (calls namespace_filter.apply_namespace_filter_to_scores)
                                │
                                ▼
                    ┌──────────────────────┐
                    │ flat_scores (filtered)│
                    │ - recalculated from  │
                    │   per-entity matches │
                    └──────────────────────┘
```

## Key Data Structures

### `judge_output.json` Schema

```json
{
  "metadata": {
    "scenario_name": "Scenario-1",
    "run": 1,
    "duration_seconds": 45.2,
    "inference_count": 12,
    "judge_model": "gpt-4o",
    "judge_provider": "azure"
  },
  "eval_result": {
    "scores": {
      "root_cause_entity": {
        "gt_entities": ["otel-demo/Service/frontend", ...],
        "predicted_entities": [
          {"entity": "otel-demo/Service/frontend", "matches_gt": true},
          {"entity": "kube-system/Pod/scheduler", "matches_gt": false}
        ],
        "calculation_precision": 0.5,
        "calculation_recall": 1.0,
        "calculation_f1": 0.667
      },
      "root_cause_reasoning": {...},
      ...
    },
    "justification": "..."
  },
  "flat_scores": {
    "root_cause_entity_precision": 0.5,
    "root_cause_entity_recall": 1.0,
    "root_cause_entity_f1": 0.667,
    "root_cause_entity_k@1_f1": 1.0,
    ...
  }
}
```

### `predicted_entities` Structure

The per-entity match data is crucial for post-hoc filtering:

```json
"predicted_entities": [
  {
    "entity": "namespace/Kind/name",
    "matches_gt": true,
    "matched_to": "gt_entity_name"  // optional
  },
  ...
]
```

## Integration with itbench_leaderboard

### How itbench_leaderboard Uses This Library

1. **Fresh Evaluation** (`judge_single_output`):
   ```python
   from itbench_evaluations import LAAJAgent, EvaluationConfig
   
   agent = LAAJAgent(config)
   eval_result = await agent.evaluate(agent_output, ground_truth)
   flat_scores = build_flat_scores_from_eval_result(eval_result)  # applies filtering
   ```

2. **Re-Aggregation** (`--aggregate-only`):
   ```python
   from itbench_evaluations.namespace_filter import apply_namespace_filter_to_scores
   
   payload = load_judge_output(judge_output_path)
   filtered_scores = apply_namespace_filter_to_scores(payload["eval_result"])
   ```

3. **Helper Functions in Leaderboard**:
   - `load_judge_output()`: Load and validate judge_output.json
   - `apply_score_filters()`: Apply namespace filtering to loaded payload
   - `build_run_result_from_judge_output()`: Create RunResult from disk
   - `build_run_result_from_run_data()`: Create RunResult from in-memory data

### Consistency Guarantees

The refactored architecture ensures:

1. **Filtering is always applied**: Whether running fresh evaluation or re-aggregating existing results, namespace filtering is applied through the same code path.

2. **Single source of truth for RunResult**: All `RunResult` objects are created through `build_run_result_from_run_data()`, ensuring consistent field mapping.

3. **Per-entity data preserved**: The `judge_output.json` stores per-entity match information, allowing scores to be recalculated without re-running the LLM.

## Evaluation Metrics

### Root Cause Entity Metrics

| Metric | Description |
|--------|-------------|
| `root_cause_entity_precision` | Correct predictions / Total predictions |
| `root_cause_entity_recall` | **Unique** GT entities found / Total GT entities |
| `root_cause_entity_f1` | Harmonic mean of precision and recall |
| `root_cause_entity_k@{k}_*` | Same metrics for top-k predictions (k=1,2,3,4,5) |

**Important**: For recall, we count **unique** GT entities matched, not total matches.
If 3 predictions all match the same 1 GT entity, recall = 1/1 = 1.0 (not 3/1 = 3.0).
This is tracked via the `matched_to` field in `predicted_entities`.

### Other Metrics

| Metric | Description |
|--------|-------------|
| `root_cause_reasoning` | Binary: did explanation match ground truth reasoning? |
| `propagation_chain` | How well did agent identify failure propagation? |
| `fault_localization_component_identification` | Component-level identification score |
| `root_cause_reasoning_partial` | Partial credit for reasoning |
| `root_cause_proximity_*` | Distance-based scoring variants |

## Design Decisions

### Why Store Per-Entity Matches?

The LLM judge outputs per-entity match data (not just aggregate scores) so that:
1. Filtering can be applied post-hoc without re-running the expensive LLM
2. Different filtering strategies can be tested
3. Detailed analysis can be performed (which entities are commonly wrong?)

### Why Namespace Filtering?

Infrastructure namespaces (kube-system, prometheus, etc.) contain monitoring and platform components. When an agent reports these as "root causes," it's technically true (they're involved in the incident) but not useful. Filtering improves precision while maintaining recall for application-level root causes.

### Why Separate itbench_evaluations from itbench_leaderboard?

- **Reusability**: Evaluation logic can be used outside the leaderboard context
- **Testing**: Evaluation can be unit tested without leaderboard infrastructure
- **Modularity**: Different leaderboards can share the same evaluation logic
- **Clarity**: Clear separation between "how to evaluate" and "how to orchestrate"

## Adding New Evaluation Criteria

1. Create a new prompt file in `prompts/`:
   ```python
   # prompts/new_criterion.py
   NEW_CRITERION_PROMPT = """..."""
   NEW_CRITERION_OUTPUT_FORMAT = """..."""
   ```

2. Register in `prompts/__init__.py`

3. Add to `EVAL_CRITERIA` in `agent.py`

4. Add handling in `LAAJAgent._evaluate_criterion()`

## Future Improvements

- [ ] Support for custom filtering strategies (configurable namespace lists)
- [ ] Caching of LLM evaluations for identical inputs
- [ ] Parallel evaluation within a single agent output
- [ ] Support for additional LLM providers beyond OpenAI-compatible APIs

