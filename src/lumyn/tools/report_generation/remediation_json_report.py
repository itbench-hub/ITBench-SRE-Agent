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
import re 
from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, Field
from crewai_tools import FileWriterTool
from crewai.tasks import TaskOutput

# Initialize the tool


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class RemediationJSONReportCustomTool(BaseTool):
    name: str = "RemediationJSONReportCustomTool"
    description: str = ("A tool that can be used to extract the JSON-formatted remediation steps from the remediation plan.")
    llm_backend: Any

    def _run(self, output: TaskOutput) -> str:
        remediation_plan = output.raw 
        
        input = remediation_plan
        system_prompt = '''You are tasked with extracting a structured JSON report from the content provided. Your output should contain only the JSON-formatted report EXACTLY in the requested schema and no other text. Do not enclose the output in markdown or any other formats, simply output the json object. 
        If the content does not contain the required information for any key, please return null for the respective keys.
        Your output should contain the following keys and values extracted from the content.
        {
        "remediation":[  # a list of remediation plans
            [   # steps in plan 1
                { "action" : <string action>
                }
            ]
        ]
        }
        '''
        try:
            response = self.llm_backend.inference(system_prompt, input)
            logger.info(f"RemediationJSONReportCustomTool NL prompt received: {remediation_plan}")
            logger.info(f"RemediationJSONReportCustomTool function arguments identified are: {response}")
            print(f"RemediationJSONReportCustomTool NL prompt received: {remediation_plan}")
            print(f"RemediationJSONReportCustomTool function arguments identified are: {response}")
            file_writer_tool = FileWriterTool()

            if "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH" in os.environ:
                directory = os.getenv("STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH")
            else:
                proj_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.getcwd())))
                directory = os.path.join(proj_dir, os.environ.get('SRE_AGENT_EVALUATION_DIRECTORY'), os.environ.get('SRE_AGENT_NAME_VERSION_NUMBER'), os.environ.get('MODEL_AGENTS').replace('/','_'), os.environ.get('INCIDENT_NUMBER') , os.environ.get('EXP_NAME'))
            try:
                response = re.findall("```(.*?)```", response, re.DOTALL)[0].removeprefix('json').strip()
            except:
                pass
            writer_result = file_writer_tool._run(filename='remediation_struct_out.json', content=response, directory=directory,overwrite="True")
            return response
        except Exception as e:
            print(f"RemediationJSONReportCustomTool error: {str(e)}")
            logger.error(f"RemediationJSONReportCustomTool error: {str(e)}")
            return None
