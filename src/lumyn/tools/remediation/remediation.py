# Copyright contributors to the ITBench project. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
import os
from typing import Any

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class RemediationCustomToolInput(BaseModel):
    diagnosis_to_remediate: str = Field(
        title="Diagnosis report.",
        description="Diagnosis report summarizing the faults that need remediation.",
    )

class RemediationCustomTool(BaseTool):
    name: str = "Remediation Tool."
    description: str = ("A tool that provides remediation steps to resolve faults identified.")
    llm_backend: Any

    def _run(self, diagnosis_to_remediate: str) -> str:
        

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "in_context_examples", "remediation.txt"),
                  "r") as f:
            rem_icl = f.read()

        input = "{}\n\n===============\n\nINPUT: {}\n".format(rem_icl, diagnosis_to_remediate)
        system_prompt = '''You are an IT incident remediation expert. Please provide a list of remediation steps to resolve the faults identified in the given diagnosis report. Provide a list of actionable, atomic, steps in natural language that can be later translated into bash commands. Do NOT provide the commands directly. Be as specific as possible, e.g., include values for parameters, if applicable. 
        If there are multiple separate remediation plans, please list them separately.'''

        try:
            response = self.llm_backend.inference(system_prompt, input)
            logger.info(f"RemediationCustomTool NL prompt received: {diagnosis_to_remediate}")
            logger.info(f"RemediationCustomTool function arguments identified are: {response}")
            print(f"RemediationCustomTool NL prompt received: {diagnosis_to_remediate}")
            print(f"RemediationCustomTool function arguments identified are: {response}")
            return response
        except Exception as e:
            print(f"RemediationCustomTool error: {str(e)}")
            logger.error(f"RemediationCustomTool error: {str(e)}")
            return None