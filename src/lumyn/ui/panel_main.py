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


import threading

import panel as pn
from crewai.agents.parser import AgentAction
from crewai.tasks.task_output import TaskOutput
from dotenv import load_dotenv

from lumyn.crew import LumynCrew

pn.extension(design="material")
load_dotenv()

user_input = None
initiate_chat_task_created = False


def initiate_chat(message):
    global initiate_chat_task_created
    initiate_chat_task_created = True

    initialize_crew(message)


def callback(contents: str, user: str, instance: pn.chat.ChatInterface):
    global initiate_chat_task_created
    global user_input

    if not initiate_chat_task_created:
        thread = threading.Thread(target=initiate_chat, args=(contents, ))
        thread.start()
    else:
        user_input = contents


def callback_crewai_task(output: TaskOutput):
    chat_interface.send(str(output.raw), user="Lumyn-SRE-Agent", respond=False)


def callback_crewai_agent(output: AgentAction):
    to_show = f"{output.thought}\n Tool: {output.tool}\n Tool Input: {output.tool_input}\n Result: {output.result}"
    chat_interface.send(to_show, user="Lumyn-SRE-Agent", respond=False)


def initialize_crew(prompt):
    try:
        callback_agent = callback_crewai_agent
        callback_task = callback_crewai_task
        inputs = {"topic": "Site Reliability Engineer (SRE) Agent", "prompt": prompt}
        result = LumynCrew(callback_agent=callback_agent, callback_task=callback_task).crew().kickoff(inputs=inputs)
        chat_interface.send("## Final Result\n" + str(result.raw), user="assistant", respond=False)
    except Exception as e:
        print(f"An error occurred: {e}")


chat_interface = pn.chat.ChatInterface(callback=callback)
chat_interface.send("What alert(s) are you observering on the IT environment?", user="System", respond=False)
chat_interface.servable()
