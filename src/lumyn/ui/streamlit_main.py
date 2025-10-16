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


# Reference: https://github.com/RexiaAI/codeExamples/blob/main/streamlit/main.py

import streamlit as st
from crewai.agents.parser import AgentAction
from crewai.tasks.task_output import TaskOutput
from dotenv import load_dotenv

from lumyn.crew import LumynCrew

load_dotenv()


def callback_crewai_task(output: TaskOutput):
    message = {"role": "Lumyn-SRE-Agent", "content": str(output.raw)}
    st.session_state.messages.append(message)
    st.chat_message("Lumyn-SRE-Agent").write(message)


def callback_crewai_agent(output: AgentAction):
    to_show = f"{output.thought}\n Tool: {output.tool}\n Tool Input: {output.tool_input}\n Result: {output.result}"
    message = {"role": "Lumyn-SRE-Agent", "content": to_show}
    st.session_state.messages.append(message)
    st.chat_message("Lumyn-SRE-Agent").write(message)


def initialize_crew(prompt):
    try:
        callback_agent = callback_crewai_agent
        callback_task = callback_crewai_task
        inputs = {"topic": "Site Reliability Engineer (SRE) Agent", "prompt": prompt}
        result = LumynCrew(callback_agent=callback_agent, callback_task=callback_task).crew().kickoff(inputs=inputs)

        message = {"role": "Lumyn-SRE-Agent", "content": "## Final Result\n" + str(result.raw)}
        st.session_state.messages.append(message)
        st.chat_message("Lumyn-SRE-Agent").write(message)
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    st.title("Lumyn - Your Site Reliability Engineering (SRE) Agent")
    # Initializing the message array (if not already present)
    if "messages" not in st.session_state:
        st.session_state["messages"] = [{
            "role": "assistant",
            "content": "What alert(s) are you observering on the IT environment?"
        }]

    # Displaying existing messages
    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    # Handling user input
    if prompt := st.chat_input():
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        initialize_crew(prompt)
