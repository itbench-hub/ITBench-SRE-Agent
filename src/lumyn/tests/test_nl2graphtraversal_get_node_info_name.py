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

from dotenv import load_dotenv

from lumyn.llm_backends.init_backend import get_llm_backend_for_tools
from lumyn.tools.graph_traversal.nl2_get_node_info import NL2GraphGetNodeInfoCustomTool

# Load environment variables from the .env file
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_nl2graph_get_node_info():
    # Instantiate the tool
    tool = NL2GraphGetNodeInfoCustomTool(llm_backend=get_llm_backend_for_tools())

    # Define a natural language query
    nl_query = "More information on front-service given the topology file at ../../../outputs/k8s_topology.json"

    # Call the tool's _run method to test it
    result = tool._run(nl_query, "../../../outputs/k8s_taxonomy.json", "../../../outputs/k8s_topology.json")
    logger.info(f"Result from the tool: \n{result}")
    print(result)


if __name__ == "__main__":
    test_nl2graph_get_node_info()
