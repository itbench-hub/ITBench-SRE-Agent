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
from typing import Any, Dict, Optional, Type

from crewai.tools.base_tool import BaseTool
from pydantic import BaseModel, Field
import time 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class WaitCustomToolInput(BaseModel):
    seconds: float = Field(
        title="Seconds",
        description="Number of seconds to wait.",
    )

class WaitCustomTool(BaseTool):
    name: str = "Wait Tool."
    description: str = ("Wait for enviroment to stabilize.")
    args_schema: Type[BaseModel] = WaitCustomToolInput

    def _run(self, seconds: float) -> None:
        try:
            time.sleep(seconds)
            logger.info(f"WaitCustomTool NL prompt received: {seconds}")
            print(f"WaitCustomTool NL prompt received: {seconds}")
            return None
        except Exception as e:
            print(f"WaitCustomTool error: {str(e)}")
            logger.error(f"WaitCustomTool error: {str(e)}")
            return None