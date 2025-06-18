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
import datetime
import json
import os
import sys
import time
import subprocess

from lumyn.crew import LumynCrew
from lumyn.tools.observability_stack.get_alerts import GetAlertsCustomTool
from lumyn.tools.kubectl.nl2kubectl import NL2KubectlCustomTool
from lumyn.tools.observability_stack.get_topology_nodes import GetTopologyNodes
from lumyn.llm_backends.init_backend import (get_llm_backend_for_tools)

# This main file is intended to be a way for your to run your
# crew locally, so refrain from adding necessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information


def format_final_op():
    if "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH" in os.environ:
        agent_op_dir = os.getenv(
            "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH")
        incident_number = os.getenv("scenario_number")
    else:
        proj_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.getcwd())))
        incident_number = os.environ.get("INCIDENT_NUMBER")
        agent_op_dir = os.path.join(
            proj_dir, os.environ.get('SRE_AGENT_EVALUATION_DIRECTORY'),
            os.environ.get('SRE_AGENT_NAME_VERSION_NUMBER'),
            os.environ.get('MODEL_AGENTS').replace('/', '_'),
            incident_number, os.environ.get('EXP_NAME'))

    op_json = {"id": f"inc-{incident_number}"}

    try:
        with open(os.path.join(agent_op_dir, 'alert_start_time.txt')) as f:
            op_json["alert_start_time"] = f.read()
    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except OSError as e:
        print(f"Could not read file: {e}")

    try:
        with open(os.path.join(agent_op_dir, 'diag_end_time.txt')) as f:
            op_json["diag_end_time"] = f.read()
    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except OSError as e:
        print(f"Could not read file: {e}")

    diag_json = {}
    rem_json = {}
    try:
        with open(os.path.join(agent_op_dir,
                               'diagnosis_struct_out.json')) as f:
            diag_json = json.load(f)
    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")

    try:
        with open(os.path.join(agent_op_dir,
                               'remediation_struct_out.json')) as f:
            rem_json = json.load(f)
    except FileNotFoundError as e:
        print(f"File not found: {e}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")

    op_json.update(diag_json)
    op_json.update(rem_json)

    with open(os.path.join(agent_op_dir, 'agent_output.json'),
              'w',
              encoding='utf-8') as f:
        json.dump(op_json, f, indent=4, separators=(',', ': '))


def run():
    """
    Run the crew.
    """
    try:
        subprocess.run('crewai reset-memories -a', shell=True, capture_output=False, text=True)
    except:
        print("no memories to clear")

    kubectl = NL2KubectlCustomTool(llm_backend=get_llm_backend_for_tools())._execute_kubectl_command("kubectl cluster-info")
    if kubectl[1] != 0:
        raise Exception("KUBECONFIG is not configured correctly.")

    while True:
        alerts = GetAlertsCustomTool()._run()
        if alerts is not None and len(alerts) > 0:
            break

    while True:
        nodes = GetTopologyNodes()._run()
        if nodes is not None:
            with open(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "tools", "report_generation", "data",
                                 "topology_nodes.json"), "w") as f:
                json.dump(nodes, f)
            if "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH" in os.environ:
                with open(
                        os.path.join(
                            os.getenv(
                                "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH"
                            ), "topology_nodes.json"), "w") as f:
                    json.dump(nodes, f)
            break

    inputs = {
        "alerts": alerts
    }

    if "STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH" in os.environ:
        eval_dir = os.getenv("STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH")
    else:
        proj_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.getcwd())))
        eval_dir = os.path.join(
            proj_dir, os.environ.get('SRE_AGENT_EVALUATION_DIRECTORY'),
            os.environ.get('SRE_AGENT_NAME_VERSION_NUMBER'),
            os.environ.get('MODEL_AGENTS').replace('/', '_'),
            os.environ.get('INCIDENT_NUMBER'), os.environ.get('EXP_NAME'))
    with open(os.path.join(eval_dir, 'alert_start_time.txt'), 'w') as f:
        f.write(datetime.datetime.now().isoformat())

    LumynCrew().crew().kickoff(inputs=inputs)
    format_final_op()


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "Problem diagnosis and remediation for an IT environment."
    }
    try:
        LumynCrew().crew().train(n_iterations=int(sys.argv[1]),
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
