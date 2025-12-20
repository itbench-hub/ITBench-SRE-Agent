"""Propagation chain evaluation prompts."""

PROPAGATION_CHAIN_PROMPT = """**{id}. Fault Propagation Chain Accuracy (Partial Credit) **
  * **Logic:**  It evaluates the model's ability to identify the causal path and establishes the **semantic components**, and **contracted paths**. It is scored using an F1-score.
  * **Method:**
      * **Calculate F1-Score:**
          * Compare the `contracted_model_path` against the `contracted_gt_path`.
          * Calculate TP (Longest Common Subsequence), Precision, Recall, and F1-Score using `calculator_tool` expressions.
  * **Justification:** Justify the F1-score by detailing the semantic components, contracted paths, TP, Precision, and Recall inputs.
  """


PROPAGATION_CHAIN_OUTPUT_FORMAT = """"propagation_chain": {
        "justification": "The F1-score is based on semantic components grouped by the specified rules. With a TP of X and path lengths Y and Z, the precision and recall are calculated.",
        "details": {
            "normalization_map": { "ad": "ad-service-1" },
            "semantic_components": { 
                "Chaos Injection Component": ["jvm-chaos-adservice-1"], 
                "Ad Service Component": ["ad-pod-1", "ad-service-1"], 
                "Frontend Service Component": ["frontend-pod-1", "frontend-service-1"] 
            },
            "contracted_gt_path": ["Chaos Injection Component", "Ad Service Component", "Frontend Service Component"],
            "contracted_model_path": ["Ad Service Component", "Frontend Service Component"],
            "lcs_components": ["Ad Service Component", "Frontend Service Component"],
            "true_positives_TP": 2,
            "model_path_length": 2,
            "gt_path_length": 3,
            }
          "precision": "calculator_tool(expression='2 / 2')",
          "recall": "calculator_tool(expression='2 / 3')",
          "calculation": "calculator_tool(expression='2 * (1.0 * 0.66) / (1.0 + 0.66)')"
      },
      """

