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


import json
import logging
import os
import time
from typing import Any, Dict, Optional, Type

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from lumyn.tools.linting.jaeger_linter import JaegerLinter
from lumyn.config.tools import NL2TracesCustomToolInputPrompt, NL2TracesCustomToolPrompt, NL2TracesSystemPrompt, NL2TracesPrompt

from .custom_function_definitions_observability_stack import fd_query_jaeger_traces
from .observability_stack_base_client import ObservabilityStackBaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NL2TracesCustomToolInput(BaseModel):
    nl_query: str = Field(
        title="NL Query",
        description=NL2TracesCustomToolInputPrompt,
    )


class NL2TracesCustomTool(BaseTool, ObservabilityStackBaseClient):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "NL2Traces Tool"
    description: str = NL2TracesCustomToolPrompt
    llm_backend: Any = None
    cache_function: bool = False
    args_schema: Type[BaseModel] = NL2TracesCustomToolInput

    def _run(self, nl_query: str) -> str:
        ObservabilityStackBaseClient.model_post_init(self)
        try:
            function_name, function_arguments, current_time = self._generate_jaeger_query(prompt=nl_query)
            services = self._get_services()
            operations = self._get_operations(function_arguments['service'])
            lint_message = JaegerLinter().lint(function_arguments, services,
                                               operations, current_time)
            if lint_message != function_arguments:
                return lint_message
            return self._summarize_traces(self._query_jaeger_traces(**function_arguments))
        except Exception as exc:
            logger.error(f"NL2Traces Tool failed with: {exc}")
            return f"NL2Traces Tool failed with: {exc}"

    def _generate_jaeger_query(self, prompt: str) -> str:
        time_micro = int(time.time_ns() / 1000)
        tools = [fd_query_jaeger_traces]
        function_name, function_arguments = self.llm_backend.inference(NL2TracesSystemPrompt, NL2TracesPrompt + prompt + f"\nThe current time in microseconds is {time_micro}", tools)
        logger.info(f"NL2Traces Tool NL prompt received: {prompt}")
        logger.info(
            f"NL2Traces Tool function arguments identified are: {function_name} {function_arguments}"
        )
        return function_name, function_arguments, time_micro

    def _query_jaeger_traces(
            self,
            service: str,
            start_time: int,
            end_time: int,
            limit: int = 5,
            error_traces_only: bool = True,
            operation: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.observability_stack_url}/jaeger/api/traces"
            if error_traces_only:
                params = {
                    "service": service,
                    "operation": operation,
                    "start": start_time,
                    "end": end_time,
                    "limit": limit,
                    "tags": json.dumps({"error": "true"})
                }
            else:
                params = {
                    "service": service,
                    "operation": operation,
                    "start": start_time,
                    "end": end_time,
                    "limit": 1
                }
            response = self._make_request("GET", url, params=params)
            logger.info(
                f"NL2Traces Tool query Jaeger traces: {response.status_code}"
            )
            logger.info(
                f"NL2Traces Tool query Jaeger traces: {response.content}")
            print(
                f"NL2Traces Tool query Jaeger traces: {response.status_code}"
            )
            print(
                f"NL2Traces Tool query Jaeger traces: {response.content}")
            return response.json()
        except Exception as e:
            print(f"Error querying Jaeger traces: {str(e)}")
            logger.error(f"Error querying Jaeger traces: {str(e)}")
            return f"Error querying Jaeger traces: {str(e)}"
        
    def _summarize_traces(self, traces):
        system_prompt = "You do trace analysis and summarization. Look at the traces given to you and provide a brief summary and analysis of them."
        traces_summary = self.llm_backend.inference(system_prompt, json.dumps(traces))
        return traces_summary
        
    def _get_services(self):
        try:
            url = f"{self.observability_stack_url}/jaeger/api/services"
            response = self._make_request("GET", url)
            logger.info(
                f"GetTracesFromObservabilityStack get_services: {response.status_code}")
            logger.info(
                f"GetTracesFromObservabilityStack get_services: {response.content}")
            print(f"GetTracesFromObservabilityStack get_services: {response.status_code}")
            print(f"GetTracesFromObservabilityStack get_services: {response.content}")
            return response.json()['data']
        except Exception as e:
            print(
                f"Error querying GetTracesFromObservabilityStack get_services: {str(e)}")
            logger.error(
                f"Error querying GetTracesFromObservabilityStack get_services: {str(e)}")
            return None

    def _get_operations(self, service):
        try:
            url = f"{self.observability_stack_url}/jaeger/api/operations"
            params = {"service": service}
            response = self._make_request("GET", url, params=params)
            logger.info(
                f"GetTracesFromObservabilityStack get_operations: {response.status_code}")
            logger.info(
                f"GetTracesFromObservabilityStack get_operations: {response.content}")
            print(
                f"GetTracesFromObservabilityStack get_operations: {response.status_code}")
            print(f"GetTracesFromObservabilityStack get_operations: {response.content}")
            return response.json()['data']
        except Exception as e:
            print(
                f"Error querying GetTracesFromObservabilityStack get_operations: {str(e)}"
            )
            logger.error(
                f"Error querying GetTracesFromObservabilityStack get_operations: {str(e)}"
            )
            return None
