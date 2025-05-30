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


#!/usr/bin/env python
import json
import sys
import subprocess
from agent_analytics.instrumentation import agent_analytics_sdk 
from lumyn.crew_finops import LumynFinOpsCrew
import os
from datetime import datetime

# This main file is intended to be a way for your to run your
# crew locally, so refrain from adding necessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information


if "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH" in os.environ:
    logs_dir_path = os.getenv("STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH")
    # log_filename = "agent_analytics_sdk_logs"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"agent_analytics_sdk_logs_{timestamp}"
    # Initialize logging with agent_analytics_sdk
    agent_analytics_sdk.initialize_logging(logs_dir_path=logs_dir_path,
                                           log_filename=log_filename)

# agent_analytics_sdk.initialize_logging()

def run():
    """
    Run the crew.
    """
    try:
        subprocess.run('crewai reset-memories -a', shell=True, capture_output=False, text=True)
    except:
        print("no memories to clear")
    inputs = {}
    LumynFinOpsCrew().crew().kickoff(inputs=inputs)


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "FinOps-related diagnosis for an IT environment."
    }
    try:
        LumynFinOpsCrew().crew().train(n_iterations=int(sys.argv[1]),
                                 filename=sys.argv[2],
                                 inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        LumynCrew().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "Problem diagnosis and remediation for an IT environment."
    }
    try:
        LumynCrew().crew().test(n_iterations=int(sys.argv[1]),
                                openai_model_name=sys.argv[2],
                                inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")
