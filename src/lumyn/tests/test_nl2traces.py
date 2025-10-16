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
from lumyn.tools.observability_stack.nl2traces import NL2TracesCustomTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

def test_nl2traces():
    nl2traces_tool = NL2TracesCustomTool(llm_backend=get_llm_backend_for_tools())
    nl_query = "get traces from the frontend service in the last hour."
    result = nl2traces_tool._run(nl_query)
    logger.info(f"Result from NL2Traces tool: \n{result}")
    print(result)

if __name__ == "__main__":
    test_nl2traces()


