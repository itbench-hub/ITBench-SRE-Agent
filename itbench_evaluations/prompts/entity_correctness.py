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
    b. Extract all entities mentioned in the `Generated Response.contributing_factor: true`, preserving their order as they appear.
    c. Normalize the entities in `Generated Response.contributing_factor` to compare them against the GT root cause(s). 
    d. For EACH predicted entity (in order), determine if it matches any GT root cause entity.
    e. Output a per-entity match list showing which predicted entities matched GT entities.
    f. Calculate the overall recall score using `calculator_tool` expressions where recall score = Number of correctly identified entities / Total entities in Ground Truth
    g. Calculate the overall precision score using `calculator_tool` expressions where precision score = Number of correctly identified entities / Total entities in Generated Response
    h. Calculate the F1 score using `calculator_tool` expressions where F1 is (2 * Recall Score * Precision Score) / (Recall Score + Precision Score).

    For example:
    - If Ground Truth mentions root cause entities [A, B, C] (3 entities)
    - If Generated Response mentions contributing factor entities [A, D, C, E] in that order
    - Per-entity matches (in order): [true, false, true, false] (A matches, D doesn't, C matches, E doesn't)
    - Recall score = calculator_tool(expression='2 / 3')
    - Precision score = calculator_tool(expression='2 / 4')
    - F1 score = calculator_tool(expression='( 2 * 2 / 3 * 2 / 4 ) / ( 2 / 3 + 2 / 4 )')
    
  * **Output:** 
    - List of GT entities
    - Ordered list of predicted entities with per-entity match boolean
    - Precision, Recall and F1 scores as calculator expressions. If there are no matching entities, output should be 0.
  * **Justification:** Brief explanation of the scoring.
  """

ROOT_CAUSE_ENTITY_OUTPUT_FORMAT = """"root_cause_entity": {
        "gt_entities": ["entity1", "entity2", ...],
        "predicted_entities": [
          {"entity": "pred1", "matches_gt": true, "matched_to": "entity1"},
          {"entity": "pred2", "matches_gt": false},
          ...
        ],
        "calculation_precision": "calculator_tool(expression='...')",
        "calculation_recall": "calculator_tool(expression='...')",
        "calculation_f1": "calculator_tool(expression='...')",
        "justification": "..."
      },
      """


