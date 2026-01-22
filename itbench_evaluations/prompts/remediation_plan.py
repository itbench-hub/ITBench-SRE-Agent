"""Remediation plan evaluation prompt.

Evaluates whether the agent's remediation plan adequately addresses
the recommended actions from the ground truth.
"""

REMEDIATION_PLAN_PROMPT = """
## Criterion {id}: Remediation Plan Adequacy

Evaluate whether the agent's remediation plan adequately addresses the recommended actions from the ground truth.

**Ground Truth Recommended Actions:**
The ground truth contains a list of recommended solutions with specific actions to resolve the incident.

**Agent's Remediation Plan:**
The agent's remediation plan contains a list of recommended actions with priorities, steps, and verification procedures.

**Evaluation Guidelines:**

1. **Action Coverage**: Does the agent's plan include actions that address the ground truth recommended solutions?
   - Each ground truth solution should be addressed by at least one action in the agent's plan
   - The agent may provide more detailed steps or additional preventive measures

2. **Action Correctness**: Are the recommended actions technically correct and appropriate?
   - Actions should directly address the root causes identified in the diagnosis
   - Actions should be feasible and safe to execute
   - Actions should not introduce new problems

3. **Priority Assessment**: Are high-priority actions correctly identified?
   - Actions addressing critical root causes should be marked as high priority
   - Actions for prevention or monitoring can be lower priority

4. **Completeness**: Does the plan provide sufficient detail?
   - Each action should have clear steps
   - Verification procedures should be included
   - Risk assessment should be present

**Scoring:**
- **1.0 (Excellent)**: All ground truth recommended actions are addressed with correct, detailed steps. Priorities are appropriate.
- **0.75 (Good)**: Most ground truth actions are addressed correctly, minor details missing or priorities slightly off.
- **0.5 (Partial)**: Some ground truth actions are addressed, but significant gaps or incorrect actions present.
- **0.25 (Poor)**: Few ground truth actions addressed, or many incorrect/inappropriate actions.
- **0.0 (Fail)**: No relevant actions, or actions would make the situation worse.

**Important Notes:**
- The agent may provide more detailed or additional actions beyond the ground truth - this is acceptable if they are relevant
- Focus on whether the core recommended actions from ground truth are adequately covered
- Consider both the action descriptions and the detailed steps provided
"""

REMEDIATION_PLAN_OUTPUT_FORMAT = """
"remediation_plan": {{
  "calculation": <float between 0.0 and 1.0>,
  "justification": "<brief explanation of the score, noting which ground truth actions are covered and any gaps>"
}}
"""

# Made with Bob
