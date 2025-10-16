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
from typing import Any, Dict, Optional

import requests
from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, Field

from .custom_function_definitions import fd_walk_path
from .graph_traversal import GraphTraversal

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NL2GraphWalkPathCustomToolInput(BaseModel):
    nl_query: str = Field(
        title="NL Query",
        description="NL query to execute.",
    )
    taxonomy_file_path: str = Field(
        title="Path to the taxonomy file",
        description="Path to the taxonomy file.",
    )
    topology_file_path: str = Field(
        title="Path to the topology file",
        description="Path to the topology file.",
    )


class NL2GraphWalkPathCustomTool(BaseTool):
    name: str = "NL2GraphWalkPathCustomTool Tool"
    description: str = ("Find the shortest path from the start node to the target node.")
    llm_backend: Any

    def _run(self, nl_query: str, taxonomy_file_path: str, topology_file_path: str) -> str:
        # Implementation goes here
        try:
            function_name, function_arguments = self._identify_function_and_arguments(
                prompt=nl_query, topology_file_path=topology_file_path)
            graph_traversal = GraphTraversal(taxonomy_file_path)
            print("NL2GraphWalkPathCustomTool function identified: ", function_name)
            print("NL2GraphWalkPathCustomTool arguments identified: ", function_arguments)

            try:
                return eval(f"graph_traversal.{function_name} (**{function_arguments})")
            except Exception as e:
                print(e)
        except Exception as exc:
            print(f"NL2GraphWalkPathCustomTool failed with: {exc}")
            logger.error(f"NL2GraphWalkPathCustomTool failed with: {exc}")
        return None

    def _identify_function_and_arguments(self, prompt: str, topology_file_path: str) -> str:

        input = f"Provide the correct function call for this action: {prompt}. The topology file is available at {topology_file_path}.\n\n"

        system_prompt = "You are a function calling bot. You are given a prompt and you need to generate a tool call based on the prompt. Make sure to fill the parameters correctly."

        tools = [fd_walk_path]

        function_name, function_arguments = self.llm_backend.inference(system_prompt, input, tools)

        logger.info(f"NL2GraphWalkPathCustomTool NL prompt received: {prompt}")
        logger.info(
            f"NL2GraphWalkPathCustomTool function arguments identified are: {function_name} {function_arguments}")
        print(f"NL2GraphWalkPathCustomTool NL prompt received: {prompt}")
        print(f"NL2GraphWalkPathCustomTool function arguments identified are: {function_name} {function_arguments}")
        return function_name, function_arguments
