"""Fault localization evaluation prompts."""

FAULT_LOCALIZATION_PROMPT = """**{id}. Fault Localization Component Identification (Strict)

* **Logic:** A true/false (1/0) metric that checks if the model correctly identified the **first semantic component to exhibit a significant failure symptom** (e.g., errors, high latency, resource saturation), as described in the ground truth propagation effects. This distinguishes between simple state changes and actual service degradation.
* **Steps:**
    1.  **Identify Ground Truth First Impacted Component:**
        * Iterate through the `GT.propagations` array in its given order, starting with the propagation originating from the root cause entity.
        * For each propagation step, examine its `effect` string to find the first clear performance failure.
        * **Performance Failure Identification:** A "performance failure" `effect` is identified by keywords such as `Error`, `Error Rate`, `High CPU`, `Latency`, `Saturation`, `Failure`, `Threshold`, `Unavailable`, `ImagePullBackOff`, `CrashLoopBackOff`. Configuration or state changes (e.g., `"flag enabled"`, `"incorrect password set"`, `"config updated"`) do **not** qualify as performance failures.
        * **The Three-Priority Rule for Identifying the Impacted Component:**
            * **Priority 1 - Explicit Component in Effect:** Read the `effect` string carefully. If it explicitly names a component experiencing the failure (e.g., "**ad pod** High CPU", "**catalogue service** is unavailable", "**frontend service** Error Rate is Above Threshold"), that named component is the first impacted component.
            * **Priority 2 - Chaos Target:** If the `source` of the propagation is a `Chaos` entity (check the entity's `kind` in GT.groups), then the `target` of that propagation is the first impacted component (as it's the first application component affected by the chaos).
            * **Priority 3 - Flagd Target:** If the `source` of the propagation is an `flagd config/flagd service` entity (check the entity's `kind` in GT.groups), then the `target` of that propagation is the first impacted component (as it's the first application component affected by the flagd service or config change).
            * **Priority 4 - Default to Target:** Only if the `effect` is ambiguous and doesn't explicitly name the failing component (e.g., "downstream errors observed"), use the `target` of the propagation as the first impacted component.
        * The semantic component is retrieved from the `semantic_components` map created in Phase 2.
        * *(Fallback): If no propagation `effect` describes a clear performance failure, the rule falls back to: the component immediately following the root cause component in the `contracted_gt_path`.*
    2.  **Check Model Output:**
        * Reference the `contracted_model_path` from Phase 2.
        * Check if the "Ground Truth First Impacted Component" (as determined by the rules above) is present anywhere in the `contracted_model_path`.
* **Output:** 1 if the component is found, 0 otherwise.
* **Justification:** Justify the decision by: (1) quoting the specific `effect` from `GT.propagations` that was used, (2) explaining which priority rule was applied to identify the component, and (3) stating whether this component was found in the model's path.
"""

FAULT_LOCALIZATION_OUTPUT_FORMAT = """"fault_localization_component_identification": {
            "calculation": <0 or 1>,
            "justification": "The first performance failure in GT.propagations is: '<effect_string>'. Using Priority X rule, the first impacted component is '<component_name>'. This component was/was not found in the model's contracted path.",
            "details": {
            "gt_first_impacted_component": "<The name of the first impacted component>",
            "effect_used": "<The effect string that identified the failure>",
            "priority_rule_applied": "<Priority 1/2/3 or Fallback>",
            "found_in_model_path": <true or false>
            }
        },
        """

