"""Reasoning correctness evaluation prompts."""

REASONING_CORRECTNESS_STEPS = """Steps to compute entity_i_reasoning score: 
        i. Extract the `condition` of every correct root cause entity from the Generated Response.
        ii. Extract the `condition` of the corresponding entities from the Ground Truth.
        iii. For each correct root cause entity, compare the model's `condition` to the GT's condition. Assign a score of:
          a. 1: if the model's `reason` is semantically equivalent to the GT's `condition`. 
          b. 0.5: if  model's `condition` describes similar resource/action but at least one key detail is missing or imprecise.
          For example, 
            GT: configmap Y featureflag X set 
            Model: configmap updated
          c. 0: incorrect or absent model `condition`.
        Save this in `entity_i_reasoning_score`.
    """

ROOT_CAUSE_REASONING_PROMPT = """**{id}. Root Cause Reasoning Accuracy**

  * **Method:**
    a. Extract the `condition` of every correct root cause entity from the Generated Response.
    {entity_correctness_steps}
    b. Extract the `condition` of the corresponding entities from the Ground Truth.
    c. For each correct root cause entity, compare the model's `condition` to the GT's condition. Assign a score of:
      I. 1: if the model's `reason` is semantically equivalent to the GT's `condition`. 
      II. 0.5: if  model's `condition` describes similar resource/action but at least one key detail is missing or imprecise.
         For example, 
            GT: configmap Y featureflag X set 
            Model: configmap updated
      III. 0: incorrect or absent model `condition`.
      Save this in `entity_i_reasoning_score`.
    d. Calculate the average of all `entity_i_reasoning_score` scores using `calculator_tool` expressions. For example, if there are `3` correct entities, with scores 0, 1 and 0.5, Average Score = calculator_tool(expression='(0+1+0.5)/3')
    If the model did not identify any root cause entity correctly, the score should be 0.
  * **Output:** Average Score `calculator_tool` expression
  * **Justification:** Brief explanation of the score for each correctly identified root cause entity.
  """

ROOT_CAUSE_REASONING_OUTPUT_FORMAT = """"root_cause_reasoning": {
        "calculation": "calculator_tool(expression='...')",
        "justification": "...",
        "details": { ... }
      },
      """

