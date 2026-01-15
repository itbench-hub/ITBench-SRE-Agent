"""Entity correctness evaluation prompts."""

ENTITY_CORRECTNESS_STEPS = """Steps to identify the correct root cause entities: 
        i. Extract all entities mentioned in the Ground Truth response have `"root_cause": true` in the `GT.groups`.
        ii. IMPORTANT: Also identify all ALIASES of these root cause entities from `GT.aliases`. Any entity that is an alias of a root cause entity is also a valid match.
        iii. Extract all entities mentioned in the`Generated Response.contributing_factor: true`. 
        iv. Normalize the entities in `Generated Response.contributing_factor` to compare them against the GT root cause(s) and their aliases.
        v. Compare the normalized entities against the GT root causes (including aliases) and identify the correct ones.
    """

ROOT_CAUSE_ENTITY_PROMPT = """**{id}. Root Cause Entity Identification (Strict)**

  * **Logic:** Compare the root cause (contributing factor) entities in the `Generated Response` against the GROUND TRUTH:
  * **Method:**
    a. Extract all entities mentioned in the Ground Truth response have `"root_cause": true` in the `GT.groups`. These are the GT root cause entities.
    b. **CRITICAL - Handle Aliases:** Check `GT.aliases` for any alias groups that contain a root cause entity. ALL entities in such alias groups should be treated as valid root cause matches. For example, if `GT.aliases` contains `["load-generator-pod-1", "load-generator-service-1", "load-generator-deployment-1"]` and `load-generator-pod-1` has `root_cause: true`, then matching ANY of these three entities counts as a correct root cause match.
    c. Extract all entities mentioned in the `Generated Response.contributing_factor: true`, preserving their order as they appear.
    d. Normalize the entities in `Generated Response.contributing_factor` to compare them against the GT root cause(s). 
    e. For EACH predicted entity (in order), determine if it matches any GT root cause entity OR any alias of a GT root cause entity.
    f. Output a per-entity match list showing which predicted entities matched GT entities.
    g. Calculate the overall recall score using `calculator_tool` expressions where recall score = Number of correctly identified entities / Total entities in Ground Truth (count each alias group only once)
    h. Calculate the overall precision score using `calculator_tool` expressions where precision score = Number of correctly identified entities / Total entities in Generated Response
    i. Calculate the F1 score using `calculator_tool` expressions where F1 is (2 * Recall Score * Precision Score) / (Recall Score + Precision Score).

    For example:
    - If Ground Truth mentions root cause entities [A, B, C] (3 entities)
    - If Generated Response mentions contributing factor entities [A, D, C, E] in that order
    - Per-entity matches (in order): [true, false, true, false] (A matches, D doesn't, C matches, E doesn't)
    - Recall score = calculator_tool(expression='2 / 3')
    - Precision score = calculator_tool(expression='2 / 4')
    - F1 score = calculator_tool(expression='( 2 * 2 / 3 * 2 / 4 ) / ( 2 / 3 + 2 / 4 )')

    Alias matching example:
    - If GT has root cause entity `pod-1` with `root_cause: true`
    - And `GT.aliases` contains `["pod-1", "service-1", "deployment-1"]`
    - If Generated Response predicts `service-1` as contributing factor
    - This should match because `service-1` is an alias of root cause entity `pod-1`
    
  * **Output:** 
    - List of GT entities (root cause entities only, not all aliases)
    - Ordered list of predicted entities with per-entity match boolean
    - Precision, Recall and F1 scores as calculator expressions. If there are no matching entities, output should be 0.
  * **Justification:** Brief explanation of the scoring, including any alias matches used.
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
