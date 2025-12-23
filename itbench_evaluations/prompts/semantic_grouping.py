"""Semantic grouping prompts for propagation chain evaluation."""

SEMANTIC_GROUPING_PROMPT = """
### **Phase 2: Creating Contracted Propagations**
      * **a. Define Semantic Components (CRITICAL LOGIC):**
          * A "Semantic Component" is a logical grouping of one or more entities from the `GT.groups` list. An entity belongs to a component based on the following **prioritized rules**:
          * **Rule 1: Isolate by Causal Kind.** Any entity whose `kind` represents an external trigger, fault injection, or monitoring event (e.g., `Chaos`, `Alert`, `Probe`) **must** be placed in its own, distinct Semantic Component. The component can be named after its kind and target (e.g., "JVM Chaos Injection Component").
          * **Rule 2: Group by Application Service.** Group entities that represent different facets of the same running application or service.
              * **Inclusion Criteria:** These components typically include Kubernetes objects like `Service`, `Pod`, `Deployment`, and `ReplicaSet`.
              * **Grouping Key:** Group them when their `filter` or `name` clearly points to the same service (e.g., filter contains `adservice`, `frontend`, etc.).
              * **Namespace Signal:** Use the namespace as a strong secondary signal. Entities belonging to the same application service component will almost always share the same namespace (e.g., `otel-demo`). An entity from a different namespace (like `chaos-mesh`) should **not** be grouped with an application service in the `otel-demo` namespace, even if the names are similar.
          * Document these component definitions in `propagation_chain.details.semantic_components`.
      * **b. Create the Contracted Ground Truth (GT) Path:**
          * Convert the sequence of GT entity IDs from `GT.propagations` into a sequence of their corresponding Semantic Component names. Remove consecutive duplicate component names to get the contracted path.
          * Store this in `propagation_chain.details.contracted_gt_path`.
      * **c. Create the Contracted Model Path:**
          * Take the `propagations` array from the `Generated Response`. Normalize each entity ID using your map.
          * Contract the resulting path by removing consecutive duplicates.
          * Store this in `propagation_chain.details.contracted_model_path`.
          -----

### **Phase 3: Scoring Rubric**"""

NO_SEMANTIC_GROUPING_PROMPT = """
### **Phase 2: Scoring Rubric**"""


