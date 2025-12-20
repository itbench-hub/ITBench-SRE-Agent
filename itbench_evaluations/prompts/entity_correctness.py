"""Entity correctness evaluation prompts."""

ENTITY_CORRECTNESS_STEPS = """Steps to identify the correct root cause entities: 
        i. Extract all entities mentioned in the Ground Truth response have `"root_cause": true` in the `GT.groups`.
        ii. Extract all entities mentioned in the`Generated Response.contributing_factor: true`. 
        iii. Normalize the entities in `Generated Response.contributing_factor` to compare them against the GT root cause(s).
        iv. Compare the normalized entities against the GT root causes and identify the correct ones.
    """

ROOT_CAUSE_ENTITY_PROMPT = """**{id}. Root Cause Entity Identification (Strict)**

  * **Logic:** Compare the root cause (contributing factor) entities in the `Generated Response` against the GROUND TRUTH:
  * **Method:**
    a. Extract all entities mentioned in the Ground Truth response have `"root_cause": true` in the `GT.groups`.
    b. Extract all entities mentioned in the`Generated Response.contributing_factor: true`. 
    c. Normalize the entities in `Generated Response.contributing_factor` to compare them against the GT root cause(s). 
    d. Calculate the recall score using `calculator_tool` expressions where recall score = Number of correctly identified entities / Total entities in Ground Truth
    e. Calculate the precision score using `calculator_tool` expressions where precision score = Number of correctly identified entities) / Total entities in Generated Response
    f. Calculate the F1 score using `calculator_tool` expressions where F1 is (2 * Recall Score * Precision Score) / (Recall Score + Precision Score).

    For example:
    - If Ground Truth mentions root cause entities [A, B, C] (3 entities)
    - If Generated Response mentions contributing factor entities [A, C, D, E] (correctly identifies A and C)
    - Recall score = calculator_tool(expression=' 2 / 3')
    - Precision score = calculator_tool(expression='2 / 4')
    - F1 score = calculator_tool(expression='( 2 * 2 / 3 * 2 / 4 ) / ( 2 / 3 + 2 / 4 )')
    
  * **Output:** Precision, Recall and F1 scores as calculator expressions. If there are no matching entities, output should be 0.
  * **Justification:** Brief explanation of the scoring. List the Ground Truth root cause entities and the contributing factor entities in the Generated Response.
  """

ROOT_CAUSE_ENTITY_OUTPUT_FORMAT = """"root_cause_entity": {
        "calculation_precision": "calculator_tool(expression='...')",
        "calculation_recall": "calculator_tool(expression='...')",
        "calculation_f1": "calculator_tool(expression='...')",
        "justification": "...",
        "details": { ... }
      },
      """

