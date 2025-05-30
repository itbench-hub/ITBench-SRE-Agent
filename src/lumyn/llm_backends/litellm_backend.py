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
import re
import json
import logging
from typing import Dict, Optional, Tuple
import litellm
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class LiteLLMBackend():
    def __init__(self, 
                 provider: str,
                 model_name: str,
                 url: str,
                 api_key: str,
                 api_version: str,
                 seed: int,
                 top_p: float,
                 temperature: float,
                 reasoning_effort: str,
                 thinking_tools: str,
                 thinking_budget_tools: int,
                 max_tokens: int,
                 extra_headers: Optional[Dict[str, str]] = None):
        self.provider = provider
        self.model_name = model_name
        self.url = url
        self.api_key = api_key
        self.api_version = api_version
        self.temperature = temperature
        self.seed = seed
        self.top_p = top_p
        self.reasoning_effort = reasoning_effort
        self.thinking_tools = thinking_tools
        self.thinking_budget_tools = thinking_budget_tools
        self.max_tokens = max_tokens
        self.extra_headers = extra_headers
        litellm.drop_params = True


    def inference(self, system_prompt: str, input: str, tools: Optional[list[any]] = None) -> str:
        logger.info(f"NL input received: {input}")
        print(f"NL input received: {input}")

        messages = []

        if self.thinking_tools == "wx":
            messages = [
                {
                    "role": "control",
                    "content": "thinking"
                },
                {
                    "role": "user",
                    "content": system_prompt + "\n" + input
                }
            ]
        else:
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": input
                }
            ]

        kwargs = {
            "model": f"{self.provider}/{self.model_name}",
            "api_key": self.api_key,
            "api_base": self.url,
            "api_version": self.api_version,
            "seed": self.seed,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": self.max_tokens,
            "messages": messages,
            "extra_headers": self.extra_headers
        }

        if tools:
            kwargs["tools"] = tools

        if self.thinking_tools == "anthropic":
            kwargs["thinking"] = { "type": "enabled", "budget_tokens": self.thinking_budget_tools }
            kwargs.pop("top_p")

        completion = litellm.completion(**kwargs)

        finish_reason = completion.choices[0].finish_reason
        if finish_reason == "tool_calls":
            function_name = completion.choices[0].message.tool_calls[0].function.name
            function_arguments = json.loads(completion.choices[0].message.tool_calls[0].function.arguments)
            return function_name, function_arguments
        else:
            return completion.choices[0].message.content