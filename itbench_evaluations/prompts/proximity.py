"""Proximity evaluation prompts (without FP normalization)."""

ROOT_CAUSE_PROXIMITY_PROMPT = """**{id}. Root Cause Proximity (No FP)**

  * **Logic:** Compute closeness between model root cause entities and the Ground-Truth (GT) root-cause entities based on number of hops between the model entity's component and any GT root-cause component (from Phase 2).
  
  * **Steps:** 
    A. *Soft Precision:*
      For each model component with root cause entity (`Generated Response.contributing_factor: true`) `PF_j (j = 1…M)`:
      a. Compute `hop_away_i,j` to every GT component `GT_i (i = 1…N)`. 
      b. Select `hop_away_j` = `min_i(hop_away_i,j)` (equivalently, keep the max score_j across N GT options).
      c. Convert to `score_j = (1 / (1 + hop_away_j))`.
      d. If PF_j is *not* on the contracted path, score_j = 0.
      e. P = (score_1 + … + score_M) / M
    B. *Soft Recall:*
      For each GT root cause entity `GT_i (i = 1…N)`:
      a. Compute `hop_away_i,j` to every model component `PF_j (j = 1…M)`. 
      b. Select `hop_away_i` = `min_j(hop_away_i,j)` (equivalently, keep the max score_i across M model options).
      c. Convert to `score_i = (1 / (1 + hop_away_i))`.
      d. If GT_i has **no** representation on the path, score_i = 0.
      e. R = (score_1 + … + score_N) / N
    C *Soft F1:*
      F = 2*P*R / (P+R)

  * **Output:** Report `calculator_tool` expressions for P, R, F1.
  * **Justification:** For every model-predicted (or GT) root-cause entity, state its chosen `hop_away_j` (or `hop_away_i`) and show how that produced `score_j` (or `score_i`). Conclude by describing how the average across the M (or N) scores yields the final result.
  """

ROOT_CAUSE_PROXIMITY_OUTPUT_FORMAT = """"root_cause_proximity_no_fp": {
    "calculation_precision": "calculator_tool(expression='(s_1 + … + s_M) / M')",
    "calculation_recall":    "calculator_tool(expression='(s'_1 + … + s'_N) / N')",
    "calculation_f1":        "calculator_tool(expression='(2 * P * R) / (P + R)')",

    "justification": "For every model entity PF_j give hop_away_j and score_j; for every GT_i give hop_away_i and score_i.  Explain how averages yield P, R and F1.",

    "precision_details": [               // MODEL side
      {
        "entity": "Valve_A",
        "is_on_path": true,
        "hop_away": 1,
        "entity_score": "calculator_tool(expression='(1/(1+1))')"
      }
      /* … */
    ],
    "recall_details": [                  // GT side
      {
        "gt_entity": "Valve_A",
        "is_on_path": true,
        "hop_away": 1,
        "entity_score": "calculator_tool(expression='(1/(1+1))')"   // s'_i
      }
      /* … */
    ]
  },
  """

