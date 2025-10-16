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
from crewai.tasks import TaskOutput
from pydantic import BaseModel, Field
from crewai_tools import FileWriterTool
import json 
import datetime
# Initialize the tool


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)



class DiagnosisJSONReportCustomTool(BaseTool):
    name: str = "DiagnosisJSONReportCustomTool"
    description: str = ("A tool that be used to structure the identified faults from the summary of diagnosis.")
    llm_backend: Any

    def _run(self, output: TaskOutput) -> str:
        diagnosis_summary = output.raw

        if "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH" in os.environ:
            directory = os.getenv("STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH")
        else:
            proj_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.getcwd())))
            directory = os.path.join(proj_dir, os.environ.get('SRE_AGENT_EVALUATION_DIRECTORY'), os.environ.get('SRE_AGENT_NAME_VERSION_NUMBER'), os.environ.get('MODEL_AGENTS').replace('/','_'), os.environ.get('INCIDENT_NUMBER') , os.environ.get('EXP_NAME'))
        with open(os.path.join(directory,'diag_end_time.txt'),'w') as f:
            f.write(datetime.datetime.now().isoformat())

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "topology_nodes.json"),
                  "r") as f:
            topology = json.load(f)
        entities = []
        for n in topology:
            try:
                entities.append(json.dumps({"entity_name":n['name'], "entity_type":n['kind'], "entity_id":n['id']}))
            except KeyError:
                pass
                  
        input = diagnosis_summary

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "diagnosis_schema_updated.json"),
                  "r") as f:
            schema = json.dumps(json.load(f))

        system_prompt = '''You are tasked with extracting a structured JSON report of the fault propogation chains from the content provided. 

        Your output should contain only the JSON-formatted report EXACTLY in the requested schema and no other text. Do not enclose the output in markdown or any other formats. Do not write the schema, only your answer. For the `id` associated with the entity you MUST use the `entity_id` associated with the entity when possible (NOT the entity_name) and, you MUST select from the entities from the following list: \n ###ENTITIES###

        The schema is:\n ###SCHEMA###

        For the fault entity, you MUST use the entity_id associated with the entity when possible (not the entity_name) and, you MUST standardize your answer using the following list: \n ###ENTITIES###

        '''.replace("###ENTITIES###",'\n'.join(entities)).replace('###SCHEMA###', schema)

        try:
            response = self.llm_backend.inference(system_prompt, input)
            logger.info(f"DiagnosisJSONReportCustomTool NL prompt received: {diagnosis_summary}")
            logger.info(f"DiagnosisJSONReportCustomTool function arguments identified are: {response}")
            print(f"DiagnosisJSONReportCustomTool NL prompt received: {diagnosis_summary}")
            print(f"DiagnosisJSONReportCustomTool function arguments identified are: {response}")
            file_writer_tool = FileWriterTool()
            
            try:
                response = re.findall("```(.*?)```", response, re.DOTALL)[0].removeprefix('json').strip()
            except:
                pass
            writer_result = file_writer_tool._run(filename='diagnosis_struct_out.json', content=response, directory=directory,overwrite="True")
            return response
        except Exception as e:
            print(f"DiagnosisJSONReportCustomTool error: {str(e)}")
            logger.error(f"DiagnosisJSONReportCustomTool error: {str(e)}")
            return None
