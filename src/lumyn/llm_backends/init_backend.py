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
from crewai import LLM
from dotenv import load_dotenv

from .litellm_backend import LiteLLMBackend

load_dotenv()

global PROVIDER_AGENTS, MODEL_AGENTS, URL_AGENTS, API_VERSION_AGENTS, API_KEY_AGENTS, REASONING_EFFORT_AGENTS, SEED_AGENTS, TOP_P_AGENTS, TEMPERATURE_AGENTS, THINKING_AGENTS, THINKING_BUDGET_AGENTS, MAX_TOKENS_AGENTS
global PROVIDER_TOOLS, MODEL_TOOLS, URL_TOOLS, API_VERSION_TOOLS, API_KEY_TOOLS, REASONING_EFFORT_TOOLS, SEED_TOOLS, TOP_P_TOOLS, TEMPERATURE_TOOLS, THINKING_TOOLS, THINKING_BUDGET_TOOLS, MAX_TOKENS_TOOLS

try:
    PROVIDER_AGENTS = os.environ["PROVIDER_AGENTS"]
except KeyError:
    PROVIDER_AGENTS = ""
    print(f"Unable to find environment variable - PROVIDER_AGENTS.")
    raise

try:
    PROVIDER_TOOLS = os.environ["PROVIDER_TOOLS"]
except KeyError:
    PROVIDER_TOOLS = ""
    print(f"Unable to find environment variable - PROVIDER_TOOLS.")
    raise

try:
    MODEL_AGENTS  = os.environ["MODEL_AGENTS"]
except KeyError:
    MODEL_AGENTS = ""
    print(f"Unable to find environment variable - MODEL_AGENTS.")
    raise

try:
    MODEL_TOOLS = os.environ["MODEL_TOOLS"]
except KeyError:
    MODEL_TOOLS = ""
    print(f"Unable to find environment variable - MODEL_TOOLS.")
    raise

try:
    URL_AGENTS = os.environ["URL_AGENTS"].rstrip("/")
except KeyError:
    URL_AGENTS = ""
    print(f"Unable to find environment variable - URL_AGENTS.")
    raise

try:
    URL_TOOLS = os.environ["URL_TOOLS"].rstrip("/")
except KeyError:
    URL_TOOLS = ""
    print(f"Unable to find environment variable - URL_TOOLS.")
    raise

try:
    API_KEY_AGENTS = os.environ["API_KEY_AGENTS"]
except KeyError:
    print("Unable to find environment variable - API_KEY_AGENTS.")
    raise

try:
    API_KEY_TOOLS = os.environ["API_KEY_TOOLS"]
except KeyError:
    print("Unable to find environment variable - API_KEY_TOOLS.")
    raise

try:
    SEED_AGENTS = int(os.environ["SEED_AGENTS"])
except KeyError:
    SEED_AGENTS = 10
    print(f"Unable to find environment variable - SEED_AGENT. Defaulting to {SEED_AGENTS}.")

try:
    SEED_TOOLS = int(os.environ["SEED_TOOLS"])
except KeyError:
    SEED_TOOLS = 10
    print(f"Unable to find environment variable - SEED_TOOLS. Defaulting to {SEED_TOOLS}.")

try:
    TOP_P_AGENTS = float(os.environ["TOP_P_AGENTS"])
except KeyError:
    TOP_P_AGENTS = 0.95
    print(f"Unable to find environment variable - TOP_P_AGENTS. Defaulting to {TOP_P_AGENTS}.")

try:
    TOP_P_TOOLS = float(os.environ["TOP_P_TOOLS"])
except KeyError:
    TOP_P_TOOLS = 0.95
    print(f"Unable to find environment variable - TOP_P_TOOLS. Defaulting to {TOP_P_TOOLS}.")

try:
    TEMPERATURE_AGENTS = float(os.environ["TEMPERATURE_AGENTS"])
except KeyError:
    TEMPERATURE_AGENTS = 0.0
    print(f"Unable to find environment variable - TEMPERATURE_AGENTS. Defaulting to {TEMPERATURE_AGENTS}.")
except ValueError as e:
    print("Incorrect TEMPERATURE_AGENTS value:", e)
    raise

try:
    TEMPERATURE_TOOLS = float(os.environ["TEMPERATURE_TOOLS"])
except KeyError:
    TEMPERATURE_TOOLS = 0.0
    print(f"Unable to find environment variable - TEMPERATURE_TOOLS. Defaulting to {TEMPERATURE_TOOLS}.")
except ValueError as e:
    print("Incorrect TEMPERATURE_TOOLS value:", e)
    raise

try:
    REASONING_EFFORT_AGENTS = str(os.environ["REASONING_EFFORT_AGENTS"]).lower()
except KeyError:
    REASONING_EFFORT_AGENTS = ""
    print(f"Unable to find environment variable - REASONING_EFFORT_AGENTS.")

try:
    REASONING_EFFORT_TOOLS = str(os.environ["REASONING_EFFORT_TOOLS"]).lower()
except KeyError:
    REASONING_EFFORT_TOOLS = ""
    print(f"Unable to find environment variable - REASONING_EFFORT_TOOLS.")

try:
    API_VERSION_AGENTS  = os.environ["API_VERSION_AGENTS"]
except KeyError:
    API_VERSION_AGENTS = ""
    print(f"Unable to find environment variable - API_VERSION_AGENTS.")

try:
    API_VERSION_TOOLS  = os.environ["API_VERSION_TOOLS"]
except KeyError:
    API_VERSION_TOOLS = ""
    print(f"Unable to find environment variable - API_VERSION_TOOLS.")

try:
    THINKING_AGENTS  = os.environ["THINKING_AGENTS"]
except KeyError:
    THINKING_AGENTS = ""
    print(f"Unable to find environment variable - THINKING_AGENTS.")

try:
    THINKING_TOOLS  = os.environ["THINKING_TOOLS"]
except KeyError:
    THINKING_TOOLS = ""
    print(f"Unable to find environment variable - THINKING_TOOLS.")

try:
    THINKING_BUDGET_AGENTS  = int(os.environ["THINKING_BUDGET_AGENTS"])
except KeyError:
    THINKING_BUDGET_AGENTS = 16000
    print(f"Unable to find environment variable - THINKING_BUDGET_AGENTS.")

try:
    THINKING_BUDGET_TOOLS  = int(os.environ["THINKING_BUDGET_TOOLS"])
except KeyError:
    THINKING_BUDGET_TOOLS = 16000
    print(f"Unable to find environment variable - THINKING_BUDGET_TOOLS.")

try:
    MAX_TOKENS_AGENTS  = int(os.environ["MAX_TOKENS_AGENTS"])
except KeyError:
    MAX_TOKENS_AGENTS = 24000
    print(f"Unable to find environment variable - MAX_TOKENS_AGENTS.")

try:
    MAX_TOKENS_TOOLS  = int(os.environ["MAX_TOKENS_TOOLS"])
except KeyError:
    MAX_TOKENS_TOOLS = 24000
    print(f"Unable to find environment variable - MAX_TOKENS_TOOLS.")

if PROVIDER_AGENTS == "watsonx" or PROVIDER_TOOLS == "watsonx":
    try:
        os.environ["WX_PROJECT_ID"]
    except KeyError:
        print(f"To use WatsonX you must provide the WX_PROJECT_ID environment variable.")
        raise


def get_llm_backend_for_agents():
    if PROVIDER_AGENTS.lower() == "rits":
        return LLM(model=f"openai/{MODEL_AGENTS}",
                   base_url=URL_AGENTS,
                   api_key="API_KEY",
                   api_version=API_VERSION_AGENTS,
                   seed=SEED_AGENTS,
                   top_p=TOP_P_AGENTS,
                   temperature=TEMPERATURE_AGENTS,
                   max_tokens=MAX_TOKENS_AGENTS,
                   extra_headers={'RITS_API_KEY': API_KEY_AGENTS}
                   )
    elif THINKING_AGENTS == "anthropic":
        return LLM(model=f"{PROVIDER_AGENTS}/{MODEL_AGENTS}",
                   base_url=URL_AGENTS,
                   api_key=API_KEY_AGENTS,
                   api_version=API_VERSION_AGENTS,
                   seed=SEED_AGENTS,
                   temperature=TEMPERATURE_AGENTS,
                   reasoning_effort=REASONING_EFFORT_AGENTS,
                   max_tokens=MAX_TOKENS_AGENTS,
                   thinking={ "type": "enabled", "budget_tokens": int(THINKING_BUDGET_TOOLS) }
                   )
    else:
        return LLM(model=f"{PROVIDER_AGENTS}/{MODEL_AGENTS}",
                   base_url=URL_AGENTS,
                   api_key=API_KEY_AGENTS,
                   api_version=API_VERSION_AGENTS,
                   seed=SEED_AGENTS,
                   top_p=TOP_P_AGENTS,
                   temperature=TEMPERATURE_AGENTS,
                   reasoning_effort=REASONING_EFFORT_AGENTS,
                   max_tokens=MAX_TOKENS_AGENTS,
                   )




def get_llm_backend_for_tools():
    if PROVIDER_TOOLS.lower() == "rits":
        return LiteLLMBackend(provider="openai",
                              model_name=MODEL_TOOLS,
                              url=URL_TOOLS,
                              api_key="API_KEY",
                              api_version=API_VERSION_TOOLS,
                              seed=SEED_TOOLS,
                              top_p=TOP_P_TOOLS,
                              temperature=TEMPERATURE_TOOLS,
                              reasoning_effort=REASONING_EFFORT_TOOLS,
                              max_tokens=MAX_TOKENS_TOOLS,
                              thinking_tools=THINKING_TOOLS,
                              thinking_budget_tools=THINKING_BUDGET_TOOLS,
                              extra_headers={ 'RITS_API_KEY': API_KEY_TOOLS }
                              )
    else:
        return LiteLLMBackend(provider=PROVIDER_TOOLS,
                              model_name=MODEL_TOOLS,
                              url=URL_TOOLS,
                              api_key=API_KEY_TOOLS,
                              api_version=API_VERSION_TOOLS,
                              seed=SEED_TOOLS,
                              top_p=TOP_P_TOOLS,
                              temperature=TEMPERATURE_TOOLS,
                              reasoning_effort=REASONING_EFFORT_TOOLS,
                              max_tokens=MAX_TOKENS_TOOLS,
                              thinking_tools=THINKING_TOOLS,
                              thinking_budget_tools=THINKING_BUDGET_TOOLS,
                              )