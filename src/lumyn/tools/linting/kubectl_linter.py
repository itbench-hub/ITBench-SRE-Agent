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


from enum import Enum
from typing import List, Set, Dict, Optional

class ResourceType(Enum):
    POD = "pod"
    DEPLOYMENT = "deployment"
    SERVICE = "service"
    CONFIGMAP = "configmap"
    SECRET = "secret"
    NAMESPACE = "namespace"
    NODE = "node"
    STATEFULSET = "statefulset"
    DAEMONSET = "daemonset"
    INGRESS = "ingress"

class KubectlAction(Enum):
    GET = "get"
    DELETE = "delete"
    DESCRIBE = "describe"
    LOGS = "logs"
    EXEC = "exec"
    PORT_FORWARD = "port-forward"
    APPLY = "apply"
    CREATE = "create"
    EDIT = "edit"
    SCALE = "scale"

class KubectlLinter:
    def __init__(self):
        self.valid_actions_map: Dict[KubectlAction, Set[ResourceType]] = {
            KubectlAction.GET: {rt for rt in ResourceType},
            KubectlAction.DELETE: {rt for rt in ResourceType},
            KubectlAction.DESCRIBE: {rt for rt in ResourceType},
            KubectlAction.LOGS: {ResourceType.POD},
            KubectlAction.EXEC: {ResourceType.POD},
            KubectlAction.PORT_FORWARD: {ResourceType.POD, ResourceType.SERVICE},
            KubectlAction.APPLY: {rt for rt in ResourceType},
            KubectlAction.CREATE: {rt for rt in ResourceType},
            KubectlAction.EDIT: {rt for rt in ResourceType},
            KubectlAction.SCALE: {
                ResourceType.DEPLOYMENT,
                ResourceType.STATEFULSET,
                ResourceType.REPLICASET
            },
        }

    def parse_command(self, command: str) -> tuple[Optional[KubectlAction], Optional[ResourceType], List[str]]:

        parts = command.split()
        if len(parts) < 3:
            return None, None, ["Command is too short"]

        try:
            action = KubectlAction(parts[1])
        except ValueError:
            return None, None, [f"Invalid action: {parts[1]}"]

        try:
            resource_type = ResourceType(parts[2].lower())
        except ValueError:
            return None, None, [f"Invalid resource type: {parts[2]}"]

        return action, resource_type, []

    def lint(self, command: str) -> List[str]:
        """Lint a kubectl command and return a list of errors."""
        errors = []

        action, resource_type, parse_errors = self.parse_command(command)
        if parse_errors:
            return parse_errors

        if action and resource_type:
            if resource_type not in self.valid_actions_map[action]:
                errors.append(
                    f"Invalid action '{action.value}' for resource type '{resource_type.value}'"
                )

        return errors