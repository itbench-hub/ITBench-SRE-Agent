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
import re
import os
from typing import Type
import subprocess
from typing import Any, Dict, Optional

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NL2ScriptInput(BaseModel):
    query: str = Field(
        title="query",
        description="This tool will write a bash script to execute the suggested remediation actions using kubectl.",
    )

class NL2ScriptCustomTool(BaseTool):
    name: str = "NL2Script Tool"
    description: str = (
        "Generate script to execute the remediation plan"
    )
    llm_backend: Any
    is_remediation: bool = False
    args_schema: Type[BaseModel] = NL2ScriptInput

    def _run(self, query: str) -> str:
        generated_script = None
        print("\n\n Inside NL2script code \n\n")
        print(query)
        if self.is_remediation:
            while True:
                try:
                    script = self._generate_script_command(prompt=query)
                    print(script)
                    user_input = input("Execute script? (Y/N)").strip().lower()
                    
                    while user_input not in ["y", "n"]:
                        print("Please enter 'Y' or 'N'.")
                        user_input = input("Execute script? (Y/N)").strip().lower()
                    
                    if user_input == "y":
                        return self._execute_bash_script(script)[0:8000]
                    else:
                        problem_description = input("What is wrong with the script?")
                        query = (
                            f"User says there is a problem with the script that you wrote:\n"
                            f"{script}\nHere is their description of the problem: {problem_description}"
                        )
                except Exception as exc:
                    logger.error(f"NL2Script Tool failed with: {exc}")
                    return f"NL2Script Tool failed with: {exc}"
        else:
            try:
                script = self._generate_script_command(prompt=query)
                print(script)
                self._execute_bash_script(script)[0:8000]
            except Exception as exc:
                    logger.error(f"NL2Script Tool failed with: {exc}")
                    return f"NL2Script Tool failed with: {exc}"


    def _generate_script_command(self, prompt: str) -> str:
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "in_context_examples", "bash.txt"),
                "r") as f:
            script_icl = f.read()

        system_prompt = f"{script_icl}\n\nGenerate script using kubectl commands for the given remediation plan. Answer with only the correct script. Do not generate anything else. The formatting should always start like this: ```#!/bin/bash\n```"

        response = self.llm_backend.inference(system_prompt, prompt)
        try:
            re_match = r'```#!\/bin\/bash\n(.*?\n)+```'
            script_of_interest = [(m.start(0), m.end(0)) for m in re.finditer(re_match, response)]
            response = response[script_of_interest[0][0]:script_of_interest[0][1]]
        except Exception as exc:
            logger.error(f"NL2ScriptCustomTool: LLM has not given correct format. Regular expression failed with: {exc}")
        logger.info(f"NL2ScriptCustomTool NL prompt received: {prompt}")
        logger.info(f"NL2ScriptCustomTool response received:\n {response}")
        print(f"NL2ScriptCustomTool NL prompt received: {prompt}")
        print(f"NL2ScriptCustomTool NL response received:\n {response}")
        return response
    
    def _execute_bash_script(self, script: str): #-> Optional[Dict[str, Any]]:
        # REQUIRE HUMAN INPUT BEFORE EXECUTION
        result = subprocess.run(script, shell=True, capture_output=True, text=True)
        print(result)
        if result.returncode == 0:
            logger.info(f"bash execution: {result.stdout}")
            print(f"bash execution: {result.stdout}")
            return result.stdout
        else:
            print(f"bash error: {result.stderr}")
            logger.error(f"bash error: {result.stderr}")
            return f"bash script execution failed: {result.stderr}"