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
from crewai_tools import FileReadTool, FileWriterTool
from dotenv import load_dotenv

from lumyn.llm_backends.init_backend import (get_llm_backend_for_agents,
                                                    get_llm_backend_for_tools)
from lumyn.tools.human_tool import HumanCustomTool
from crewai_tools import FileReadTool
from lumyn.tools.observability_stack.clickhouse_nl2sql import NL2SQLClickHouseCustomTool
from lumyn.tools.anomaly_detection import AnomalyDetectionCustomTool

load_dotenv()


@CrewBase
class LumynFinOpsCrew():

    agents_config = os.path.join(
            os.getenv("AGENT_TASK_DIRECTORY"), "finops_agents.yaml")
    tasks_config = os.path.join(
            os.getenv("AGENT_TASK_DIRECTORY"), "finops_tasks.yaml")

    def __init__(self, callback_agent=None, callback_task=None):
        self.callback_task = None
        self.callback_agent = None

        try:
            if callback_agent is not None and callback_task is not None:
                self.callback_task = callback_task
                self.callback_agent = callback_agent
        except KeyError as e:
            print("No handlers (or one of the handlers) spotted at this time:",
                  e)

    @agent
    def finops_data_query_agent(self) -> Agent:
        return Agent(config=self.agents_config["finops_data_query_agent"],
                     llm=get_llm_backend_for_agents(),
                     tools=[
                        NL2SQLClickHouseCustomTool(llm_backend=get_llm_backend_for_tools()),
                        # FileWriterTool(file_path="./data/data_intermediate.csv")
                     ],
                     allow_delegation=False,
                     max_iter=20,
                     step_callback=self.callback_agent,
                     verbose=True,
                     respect_context_window=True,
                     human_input=False)
    
    @agent
    def finops_anomaly_detection_agent(self) -> Agent:
        return Agent(config=self.agents_config["finops_anomaly_detection_agent"],
                     llm=get_llm_backend_for_agents(),
                     tools=[
                        NL2SQLClickHouseCustomTool(llm_backend=get_llm_backend_for_tools()),
                        AnomalyDetectionCustomTool()
                     ],
                     allow_delegation=False,
                     max_iter=20,
                     step_callback=self.callback_agent,
                     verbose=True,
                     respect_context_window=True,
                     human_input=False)

    @task
    def finops_human_input_query_task(self) -> Task:
        return Task(
            config=self.tasks_config["finops_human_input_query_task"],
            verbose=True,
            tools=[
                HumanCustomTool()
                # FileReadTool(file_path='finops_prompt.txt')

            ])

    @task
    def finops_data_query_task(self) -> Task:
        return Task(
            config=self.tasks_config["finops_data_query_task"],
            verbose=True,
            tools=[
                NL2SQLClickHouseCustomTool(llm_backend=get_llm_backend_for_tools()),
            ],
            human_input=False)
    
    # @task
    # def finops_anomaly_detection_task(self) -> Task:
    #     return Task(
    #         config=self.tasks_config["finops_anomaly_detection_task"],
    #         verbose=True,
    #         tools=[
    #             # FileReadTool(file_path="./data/focus_data_table.csv", verbose=False),
    #             NL2SQLClickHouseCustomTool(llm_backend=get_llm_backend_for_tools()),
    #             # FileWriterTool(file_path="./data/data_intermediate.csv"),
    #             AnomalyDetectionCustomTool()
    #         ],
    #         human_input=False)

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
