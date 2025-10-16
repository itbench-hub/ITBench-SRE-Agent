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


import json
import networkx as nx
import itertools


class GraphTraversal():

    def __init__(self, taxonomy_file_path, type="type"):
        self.Gx = self.read_graph(taxonomy_file_path)
        self.dests = []
        self.type_attribute = type

    def read_graph(self, file_path):
        with open(file_path, "r") as f:
            data = json.load(f)

        G = nx.Graph()

        if isinstance(data["nodes"], list):
            for node in data["nodes"]:
                G.add_node(node["id"], **node)

        if isinstance(data["nodes"], dict):
            for node in data["nodes"].values():
                G.add_node(node["id"], **node)

        # Add edges
        if "edges" in data.keys():
            edge_property = "edges"
        else:
            edge_property = "links"

        for edge in data[edge_property]:
            if "destination" in edge.keys():
                G.add_edge(edge["source"], edge["destination"], relation=edge["relation"])  # **edge)
            if "target" in edge.keys():
                G.add_edge(edge["source"], edge["target"], relation=edge["relation"])  # **edge)
            if "from" in edge.keys():
                G.add_edge(edge["from"], edge["to"], relation=edge["relation"])  # **edge)
        return G

    def get_nodes_by_attr(self, topology, attr, val):
        G = self.read_graph(topology)
        return [a["id"] for n, a in G.nodes(data=True) if a.get(attr) == val]

    def get_neighbors_with_attr(self, G, nid, k, v):
        return [n for n in nx.neighbors(G, nid) if G.nodes[n][k] == v]

    def get_neighbors(self, topology, node_id):
        G = self.read_graph(topology)
        return [(n, G.nodes[n][self.type_attribute]) for n in nx.neighbors(G, node_id)]

    def walk_path(self, topology, start_id, start_node_type, target_node_type):

        G = self.read_graph(topology)
        
        paths = [p for p in nx.all_shortest_paths(self.Gx, start_node_type, target_node_type)]

        path = paths[0]

        self.dests = []
        self._walk_path(G, [start_id], path, depth=0)

        return list(itertools.chain(*self.dests))

    def _walk_path(self, G, nodes, path, depth=0):
        depth += 1
        if depth == len(path):
            self.dests.append(nodes)
            return
        for node in nodes:
            neighbors = self.get_neighbors_with_attr(G, node, self.type_attribute, path[depth])
            self._walk_path(G, neighbors, path, depth)

    def get_node_info_by_name(self, topology, node_name):
        G = self.read_graph(topology)
        return [G.nodes[n] for n in G.nodes if G.nodes[n]["name"] == node_name]

    def check_directly_connected(self, topology, node_id1, node_id2):
        G = self.read_graph(topology)
        return node_id2 in [n for n in nx.neighbors(G, node_id1)]
