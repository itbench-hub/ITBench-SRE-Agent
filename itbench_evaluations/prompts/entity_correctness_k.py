"""Entity correctness @k evaluation prompts."""

ROOT_CAUSE_ENTITY_K_PROMPT = """**{id}. Root Cause Entity Identification@k (Strict)**

  * **Logic:** Compare the root cause (contributing factor) entities in the `Generated Response` against the GROUND TRUTH:
  * **Method:**
    a. Extract all entities mentioned in the Ground Truth response have `"root_cause": true` in the `GT.groups`.
    b. Extract the first k={k} entities mentioned in the`Generated Response` with `contributing_factor: true`. 
    c. Normalize the entities in `Generated Response.contributing_factor` to compare them against the GT root cause(s). 
    d. Calculate the recall score using `calculator_tool` expressions where recall score = Number of correctly identified entities in the first k={k} predictions/ Total entities in Ground Truth
    e. Calculate the precision score using `calculator_tool` expressions where precision score = Number of correctly identified entities in the first k={k} predictions) / Total entities in Generated Response
    f. Calculate the F1 score using `calculator_tool` expressions where F1 is (2 * Recall Score * Precision Score) / (Recall Score + Precision Score).

    For example:
    - If Ground Truth mentions root cause entities [A, B, C] (3 entities)
    - If k=4 and the Generated Response mentions first 4 contributing factor entities as [A, C, D, E] (correctly identifies A and C)
    - Recall score = calculator_tool(expression=' 2 / 3')
    - Precision score = calculator_tool(expression='2 / 4')
    - F1 score = calculator_tool(expression='( 2 * 2 / 3 * 2 / 4 ) / ( 2 / 3 + 2 / 4 )')
    
  * **Output:** Precision, Recall and F1 scores as calculator expressions. If there are no matching entities, output should be 0.
  * **Justification:** Brief explanation of the scoring. List the Ground Truth root cause entities and the first k={k} contributing factor entities in the Generated Response.
  """

ROOT_CAUSE_ENTITY_K_OUTPUT_FORMAT = """"root_cause_entity_k": {
        "calculation_precision": "calculator_tool(expression='...')",
        "calculation_recall": "calculator_tool(expression='...')",
        "calculation_f1": "calculator_tool(expression='...')",
        "justification": "...",
        "details": { ... }
      },
      """

