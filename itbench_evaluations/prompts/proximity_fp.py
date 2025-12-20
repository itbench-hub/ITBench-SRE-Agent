"""Proximity evaluation prompts (with FP normalization)."""

ROOT_CAUSE_PROXIMITY_FP_PROMPT = """**{id}. Root Cause Proximity (With FP)**

  * **Logic:** Compute closeness between model root cause entities and the Ground-Truth (GT) root-cause entities based on number of hops between the model entity's component and any GT root-cause component (from Phase 2). Normalize distance by `gt_path_length`, length of the contracted GT path.
  * **Steps:** 
  A. *Soft Precision:*
      For each model component with root cause entity (`Generated Response.contributing_factor: true`) `PF_j (j = 1…M)`:
      a. Compute `hop_away_i,j` to every GT component `GT_i (i = 1…N)`. 
      b. Select `hop_away_j` = `min_i(hop_away_i,j)` (equivalently, keep the max score_j across N GT options).
      c. Convert to `score_j = (1 / (1 + hop_away_j / gt_path_length))`.
      d. If PF_j is *not* on the contracted path, score_j = 0.
      e. P = (score_1 + … + score_M) / M
    B. *Soft Recall:*
      For each GT root cause entity `GT_i (i = 1…N)`:
      a. Compute `hop_away_i,j` to every model component `PF_j (j = 1…M)`. 
      b. Select `hop_away_i` = `min_j(hop_away_i,j)` (equivalently, keep the max score_i across M model options).
      c. Convert to `score_i = (1 / (1 + hop_away_i / gt_path_length))`.
      d. If GT_i has **no** representation on the path, score_i = 0.
      e. R = (score_1 + … + score_N) / N
    C *Soft F1:*
      F = 2*P*R / (P+R)
  * **Output:** Report `calculator_tool` expressions for P, R, F1.
  * **Justification:** For every model-predicted (or GT) root-cause entity, state its chosen `hop_away_j` (or `hop_away_i`) and show how that produced `score_j` (or `score_i`). Conclude by describing how the average across the M (or N) scores yields the final result.
  """




ROOT_CAUSE_PROXIMITY_FP_OUTPUT_FORMAT = """"root_cause_proximity_with_fp": {
    "gt_path_length": 5,
    "calculation_precision": "calculator_tool(expression='(s_1 + … + s_M) / M')",
    "calculation_recall":    "calculator_tool(expression='(s'_1 + … + s'_N) / N')",
    "calculation_f1":        "calculator_tool(expression='(2 * P * R) / (P + R)')",

    "justification": "State gt_path_length, list hop distances, show how the (1 / (1 + hop/gt_path_length)) rule produced each score, then average.",

    "precision_details": [
      {
        "entity": "Valve_A",
        "is_on_path": true,
        "hop_away": 1,
        "entity_score": "calculator_tool(expression='(1 / (1 + 1/5))')"
      }
      /* … */
    ],
    "recall_details": [
      {
        "gt_entity": "Valve_A",
        "is_on_path": true,
        "hop_away": 1,
        "entity_score": "calculator_tool(expression='(1 / (1 + 1/5))')"   // s'_i
      }
      /* … */
    ]
  }
  """
