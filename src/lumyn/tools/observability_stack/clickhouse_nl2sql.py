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
from typing import Any, List, Type

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from lumyn.tools.linting.sql_linter import SQLLinter
from lumyn.config.tools import NL2SQLCustomToolInputPrompt, NL2SQLCustomToolPrompt, NL2SQLSystemPrompt, NL2SQLPrompt

from .clickhouse_base_client import ClickHouseBaseClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NL2SQLClickHouseCustomToolInput(BaseModel):
    nl_query: str = Field(
        title="NL2SQLClickHouse Query",
        description=NL2SQLCustomToolInputPrompt,
    )


class NL2SQLClickHouseCustomTool(BaseTool, ClickHouseBaseClient):
    name: str = "NL2SQLClickHouse Tool"
    description: str = NL2SQLCustomToolPrompt
    llm_backend: Any = None
    cache_function: bool = False
    args_schema: Type[BaseModel] = NL2SQLClickHouseCustomToolInput

    def _run(self, nl_query: str) -> str:
        ClickHouseBaseClient.model_post_init(self)
        try:
            function_arguments = self._generate_sql_query(prompt=nl_query)
            # lint_message = SQLLinter.lint(function_arguments, dialect="mysql")
            # if lint_message != function_arguments:
            #     # print("======================")
            #     # print("Linter response",lint_message)
            #     # print("==================")
            #     return lint_message
            return self._query_clickhouse(function_arguments)
        except Exception as exc:
            logger.error(f"NL2SQLClickHouse Tool failed with: {exc}")
            return f"NL2SQLClickHouse Tool failed with: {exc}"

    def _generate_sql_query(self, prompt: str) -> str:
        time_in_seconds = time.time()
        function_arguments = self.llm_backend.inference(NL2SQLSystemPrompt, NL2SQLPrompt + prompt + f"\nThe current time in seconds is {time_in_seconds}")
        logger.info(f"NL2SQLClickHouse Tool NL prompt received: {prompt}")
        logger.info(f"NL2SQLClickHouse Tool function arguments identified are: {function_arguments}")
        print(f"NL2SQLClickHouse Tool NL prompt received: {prompt}")
        print(f"NL2SQLClickHouse Tool function arguments identified are: {function_arguments}")
        response = re.search(r"```sql\n(.*?)\n```", function_arguments, re.DOTALL).group(1).strip()
        return response

    def _query_clickhouse(self, query: str) -> List:
        # print("***************before running query**********")
        try:
            output=self._query(query)
            return output
        except Exception as e:
            print(f"Error querying ClickHouse: {str(e)}")
