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
import json
import os
import re
import time
from typing import Any, Dict, Optional, Type

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from lumyn.tools.linting.promql_linter import PromQLLinter
from lumyn.config.tools import NL2MetricsCustomToolInputPrompt, NL2MetricsCustomToolPrompt, NL2MetricsSystemPrompt, NL2MetricsPrompt

from .observability_stack_base_client import ObservabilityStackBaseClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NL2MetricsCustomToolInput(BaseModel):
    nl_query: str = Field(
        title="PromQL Query",
        description=NL2MetricsCustomToolInputPrompt,
    )


class NL2MetricsCustomTool(BaseTool, ObservabilityStackBaseClient):
    name: str = "NL2Metrics Tool"
    description: str = NL2MetricsCustomToolPrompt
    llm_backend: Any = None
    cache_function: bool = False
    args_schema: Type[BaseModel] = NL2MetricsCustomToolInput

    def _run(self, nl_query: str) -> str:
        ObservabilityStackBaseClient.model_post_init(self)
        try:
            function_arguments = self._generate_promql_query(prompt=nl_query)
            lint_message = PromQLLinter.lint(function_arguments)
            if lint_message != function_arguments:
                return lint_message
            return self._summarize_metrics(self._query_prometheus_metrics(function_arguments))
        except Exception as exc:
            logger.error(f"NL2Metrics Tool failed with: {exc}")
            return f"NL2Metrics Tool failed with: {exc}"

    def _generate_promql_query(self, prompt: str) -> str:
        time_in_seconds = time.time()
        function_arguments = self.llm_backend.inference(NL2MetricsSystemPrompt, NL2MetricsPrompt + prompt + f"\nThe current time in seconds is {time_in_seconds}")
        logger.info(f"NL2Metrics Tool NL prompt received: {prompt}")
        logger.info(f"NL2Metrics Tool function arguments identified are: {function_arguments}")
        print(f"NL2Metrics Tool NL prompt received: {prompt}")
        print(f"NL2Metrics Tool function arguments identified are: {function_arguments}")
        response = re.search(r"```promql\n(.*?)\n```", function_arguments, re.DOTALL).group(1).strip()
        return response

    def _query_prometheus_metrics(self, query: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"{self.observability_stack_url}/prometheus/api/v1/query"
            params = {"query": query}

            response = self._make_request("GET", url, params=params)
            logger.info(f"NL2Metrics Tool query prometheus metrics: {response.status_code}")
            print(f"NL2Metrics Tool query prometheus metrics: {response.content}")
            return response.json()
        except Exception as e:
            print(f"Error querying Prometheus metrics: {str(e)}")
            logger.error(f"Error querying Prometheus metrics: {str(e)}")
            return f"Error querying Prometheus metrics: {str(e)}"

    def _summarize_metrics(self, metrics):
        system_prompt = "You do metrics analysis and summarization. Look at the metrics given to you and provide a brief summary and analysis of them."
        metrics_summary = self.llm_backend.inference(system_prompt, json.dumps(metrics))
        return metrics_summary
