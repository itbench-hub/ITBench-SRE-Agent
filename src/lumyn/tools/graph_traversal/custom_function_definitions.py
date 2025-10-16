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


fd_walk_path = {
    "type": "function",
    "function": {
        "name": "walk_path",
        "description": "get the target node ids connected from the start node type, following the shortest path from the start node to the target node type.",
        "parameters": {
            "type": "object",
            "properties": {
                "topology": {
                    "type": "string",
                    "description": "nodex graph json filename that stores the kubernetes topology",
                },
                "start_id": {
                    "type": "string",
                    "description": "start node id",
                },
                "start_node_type": {
                    "type": "string",
                    "description": "start node type",
                },
                "target_node_type": {
                    "type": "string",
                    "description": "target node type",
                }
            },
            "required": ["topology", "start_id", "start_node_type", "target_node_type"],
            "additionalProperties": False
        }
    }
}

fd_get_node_info_by_name = {
    "type": "function",
    "function": {
        "name": "get_node_info_by_name",
        "description": "get information of the node specified as node name",
        "parameters": {
            "type": "object",
            "properties": {
                "topology": {
                    "type": "string",
                    "description": "nodex graph json filename that stores the topology",
                },
                "node_name": {
                    "type": "string",
                    "description": "node name to provide the information",
                },
            },
            "required": ["topology", "node_name"],
            "additionalProperties": False
        }
    }
}

fd_get_neighbors = {
    "type": "function",
    "function": {
        "name": "get_neighbors",
        "description": "get neighbors of node_id using the topology data. the expected node type should not be specified.",
        "parameters": {
            "type": "object",
            "properties": {
                "topology": {
                    "type": "string",
                    "description": "nodex graph json filename that stores the kubernetes topology",
                },
                "node_id": {
                    "type": "string",
                    "description": "node id to find the neighbors that are connected to it",
                },
            },
            "required": ["topology", "node_id"],
            "additionalProperties": False
        }
    }
}

fd_check_directly_connected = {
    "type": "function",
    "function": {
        "name": "check_directly_connected",
        "description": "this function checks if node id 1 and node id 2 are directly connected given the topology.",
        "parameters": {
            "type": "object",
            "properties": {
                "topology": {
                    "type": "string",
                    "description": "nodex graph json filename that stores the kubernetes topology",
                },
                "node_id1": {
                    "type": "string",
                    "description": "node id to find if it is directly connected to node id 2",
                },
                "node_id2": {
                    "type": "string",
                    "description": "node id to find if it is directly connected to node id 1",
                },
            },
            "required": ["topology", "node_id1", "node_id2"],
            "additionalProperties": False
        }
    }
}
