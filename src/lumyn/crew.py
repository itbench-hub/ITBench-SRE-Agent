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


import os

# from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction
from crewai import LLM, Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from dotenv import load_dotenv

from lumyn.llm_backends.init_backend import (get_llm_backend_for_agents,
                                                    get_llm_backend_for_tools)
from lumyn.tools.code_generation.nl2script import NL2ScriptCustomTool
from lumyn.tools.observability_stack.get_alerts import GetAlertsCustomTool
from lumyn.tools.observability_stack.nl2metrics import NL2MetricsCustomTool
from lumyn.tools.observability_stack.nl2traces import NL2TracesCustomTool
from lumyn.tools.kubectl.nl2kubectl import NL2KubectlCustomTool
from lumyn.tools.remediation.remediation import RemediationCustomTool
from lumyn.tools.remediation.wait import WaitCustomTool
from lumyn.tools.report_generation.code_json_report import \
    CodeJSONReportCustomTool
from lumyn.tools.report_generation.diagnosis_json_report import \
    DiagnosisJSONReportCustomTool
from lumyn.tools.report_generation.remediation_json_report import \
    RemediationJSONReportCustomTool

load_dotenv()


@CrewBase
class LumynCrew():

    def __init__(self, callback_agent=None, callback_task=None):
        self.callback_task = None
        self.callback_agent = None

        if os.getenv("AGENT_TASK_DIRECTORY"):
            print("Using custom configuration...")
            self.agents_config = os.path.join(
                os.getenv("AGENT_TASK_DIRECTORY"), "agents.yaml")
            self.tasks_config = os.path.join(os.getenv("AGENT_TASK_DIRECTORY"),
                                             "tasks.yaml")
        else:
            # TODO: Switch to logging
            print("Using default configuration...")
            self.agents_config = "config/agents.yaml"
            self.tasks_config = "config/tasks.yaml"

        try:
            if callback_agent is not None and callback_task is not None:
                self.callback_task = callback_task
                self.callback_agent = callback_agent
        except KeyError as e:
            print("No handlers (or one of the handlers) spotted at this time:",
                  e)

    @agent
    def sre_diagnosis_agent(self) -> Agent:
        return Agent(config=self.agents_config["sre_diagnosis_agent"],
                     llm=get_llm_backend_for_agents(),
                     tools=[
                        GetAlertsCustomTool(),
                        NL2KubectlCustomTool(llm_backend=get_llm_backend_for_tools()),
                        NL2MetricsCustomTool(llm_backend=get_llm_backend_for_tools()),
                        NL2TracesCustomTool(llm_backend=get_llm_backend_for_tools()),
                     ],
                     allow_delegation=False,
                     max_iter=20,
                     step_callback=self.callback_agent,
                     verbose=True,
                     respect_context_window=True,
                     human_input=False)

    @agent
    def sre_remediation_agent(self) -> Agent:
        return Agent(config=self.agents_config["sre_remediation_agent"],
                     llm=get_llm_backend_for_agents(),
                     tools=[],
                     allow_delegation=False,
                     max_iter=20,
                     step_callback=self.callback_agent,
                     verbose=True,
                     respect_context_window=True,
                     human_input=False)

    @task
    def sre_diagnosis_tool_task(self) -> Task:
        return Task(
            config=self.tasks_config["sre_diagnosis_tool_task"],
            verbose=True,
            tools=[
                GetAlertsCustomTool(),
                NL2KubectlCustomTool(llm_backend=get_llm_backend_for_tools()),
                NL2MetricsCustomTool(llm_backend=get_llm_backend_for_tools()),
                NL2TracesCustomTool(llm_backend=get_llm_backend_for_tools()),
            ],
            human_input=False,
            callback=DiagnosisJSONReportCustomTool(
                llm_backend=get_llm_backend_for_tools())._run,
            step_callback=self.callback_task)

    @task
    def sre_remediation_task(self) -> Task:
        tools = [
            GetAlertsCustomTool(),
            RemediationCustomTool(llm_backend=get_llm_backend_for_tools()),
            WaitCustomTool()
        ]

        return Task(
            config=self.tasks_config["sre_remediation_task"],
            verbose=True,
            tools=[
                RemediationCustomTool(llm_backend=get_llm_backend_for_tools()),
            ],
            human_input=False,
            context=[self.sre_diagnosis_tool_task()],
            callback=RemediationJSONReportCustomTool(
                llm_backend=get_llm_backend_for_tools())._run,
            step_callback=self.callback_task)

    @task
    def sre_remediation_code_task(self) -> Task:
        tools = []

        if os.getenv("GOD_MODE", "False") == "True":
            # tools.append(  NL2ScriptCustomTool(llm_backend=get_llm_backend_for_tools()))
            tools.append(
                NL2KubectlCustomTool(llm_backend=get_llm_backend_for_tools()))
        else:
            # tools.append(  NL2ScriptCustomTool(llm_backend=get_llm_backend_for_tools(), is_remediation=True))
            tools.append(
                NL2KubectlCustomTool(llm_backend=get_llm_backend_for_tools(),
                                     is_remediation=True))

        return Task(config=self.tasks_config["sre_remediation_task"],
                    verbose=True,
                    tools=tools,
                    human_input=False,
                    context=[self.sre_diagnosis_tool_task()],
                    callback=RemediationJSONReportCustomTool(
                        llm_backend=get_llm_backend_for_tools())._run,
                    step_callback=self.callback_task)

    @crew
    def crew(self) -> Crew:
        if os.getenv("MODEL_EMBEDDING"):
            if os.getenv("PROVIDER_AGENTS") == "azure":
                memory = True
                embedder = {
                    "provider": "azure",
                    "config": {
                        "api_type": "azure",
                        "api_key": os.getenv("API_KEY_AGENTS"),
                        "api_base": os.getenv("URL_EMBEDDING"),
                        "api_version": os.getenv("API_VERSION_EMBEDDING"),
                        "model_name": os.getenv("MODEL_EMBEDDING")
                    }
                }
            elif os.getenv("PROVIDER_AGENTS") == "watsonx":
                memory = True
                embedder = {
                    "provider": "watson",
                    "config": {
                        "model": os.getenv("MODEL_EMBEDDING"),
                        "api_url": os.getenv("URL_EMBEDDING"),
                        "api_key": os.getenv("API_KEY_AGENTS"),
                        "project_id": os.getenv("WX_PROJECT_ID"),
                    }
                }
        else:
            memory = False
            embedder = None

        return Crew(agents=self.agents,
                    tasks=self.tasks,
                    process=Process.sequential,
                    memory=memory,
                    embedder=embedder,
                    verbose=True)
