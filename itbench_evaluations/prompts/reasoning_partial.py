"""Partial reasoning evaluation prompts."""

ROOT_CAUSE_REASONING_PARTIAL_PROMPT = """**{id}. Root Cause Reasoning, Partial (Partial Credit)**

  * **Logic:** This metric provides a more forgiving score for reasoning. For each model root cause entity `i`, if `i` matches a ground truth root cause entity, this score is same as the `entity_i_reasoning_score`. Otherwise, it awards partial credit if the model correctly analyzed a downstream symptom when it missed the root cause entity.
  * **Method:** 
    For each root cause entity `i` in the Generated Response,
      I. *if `i` matches a ground truth entity*, this score equals `entity_i_reasoning_score`.
        {entity_and_reasoning_steps}
      II. Else,: Compute partial credit using the steps below.
      * **Partial Credit Formula Steps:**
        A.  **Identify Model's Focus:** The normalized entity from `contributing_factor`.
        B.  **Verify Symptom on Path:** Ensure the **semantic component** of the model's focus entity is on the **contracted GT path** (both from Phase 2).
        C.  **Calculate `hop_away`:** This is the number of steps on the **contracted semantic path** (from Phase 2) from the true root cause *component* to the model-identified symptom's *component*.
        D.  **Determine `SymptomReasoningCorrectness`:** An expert assessment of how well the model's `condition` describes the `condition` of the symptom component it identified. It should be either 0 (incorrect), 0.5 (generally correct but missing key details) or 1 (semantically equivalent).
        E: Provide the calculation `(1 / (1 + hop_away)) * SymptomReasoningCorrectness` as a `calculator_tool` expression.
      III. Calculate the max over all root cause entities as a `calculator_tool` expression.
  * **Output:** Max over all root cause entities as a `calculator_tool` expression.
  * **Justification:** Explain the score based on the method. If partial credit was calculated, detail the `hop_away` and `SymptomReasoningCorrectness`.
  """

ROOT_CAUSE_REASONING_PARTIAL_OUTPUT_FORMAT = """"root_cause_reasoning_partial": {
    "calculation": "calculator_tool(expression='max(pc_1 , pc_2 , … , pc_M)')",
    "justification": "Entity "Valve_A": Metric 1 was correct, so we copy Metric 2's score (pc_1 = 1). "
                     "Entity "Sensor_B": Metric 1 was wrong but the symptom lies 2 hops away on the contracted path; "
                     "SymptomReasoningCorrectness = 0.5. Partial credit pc_2 = (1/(1+2))*0.5. "
                     "Average score = calculator_tool(expression='max(1 , (1/(1+2))*0.5)').",
    "details": [
      {
        "entity": "Valve_A",
        "metric1_is_correct": true,
        "hop_away": null,
        "SymptomReasoningCorrectness": null,
        "entity_score": "calculator_tool(expression='1')"
      },
      {
        "entity": "Sensor_B",
        "metric1_is_correct": false,
        "hop_away": 2,
        "SymptomReasoningCorrectness": 0.5,
        "entity_score": "calculator_tool(expression='(1/(1+2))*0.5')"
      }
    ]
  },
  """

