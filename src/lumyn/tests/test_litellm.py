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


import litellm
import os


provider = os.environ["PROVIDER_AGENTS"]
model_name = os.environ["MODEL_AGENTS"]
api_key = os.environ["API_KEY_AGENTS"]
url = os.environ["URL_AGENTS"]


def inference(input: str) -> str:
    kwargs = {
        "model": f"{provider}/{model_name}",
        "api_key": api_key,
        "api_base": url,
        #"temperature": 1,
        #"max_tokens": 20000,
        #"thinking": { "type": "enabled", "budget_tokens": 16000 }
    }

    messages = [
        # {
        #     "role": "system",
        #     "content": "test system prompt"
        # },
        {
            "role": "user", 
            "content": input
        }
    ]

    kwargs["messages"] = messages

    completion = litellm.completion(**kwargs)
    print(completion)
    return completion.choices[0].message.content


print(inference("what is the fastest way to travel to every city in the US"))