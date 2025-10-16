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


fd_query_loki_logs = {
    "type": "function",
    "function": {
        "name": "query_loki_logs",
        "description": "query loki logs",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The LogQL query to perform.",
                },
                "limit": {
                    "type":
                    "integer",
                    "description":
                    "The max number of entries to return. It defaults to 100. Only applies to query types which produce a stream (log lines) response.",
                },
                "start": {
                    "type":
                    "string",
                    "description":
                    "The start time for the query as a nanosecond Unix epoch or another supported format. Defaults to one hour ago. Loki returns results with timestamp greater or equal to this value.",
                },
                "end": {
                    "type":
                    "string",
                    "description":
                    "The end time for the query as a nanosecond Unix epoch or another supported format. Defaults to now. Loki returns results with timestamp lower than this value.",
                },
                "since": {
                    "type":
                    "string",
                    "description":
                    "A duration used to calculate start relative to end. If end is in the future, start is calculated as this duration before now. Any value specified for start supersedes this parameter.",
                },
                "step": {
                    "type":
                    "string",
                    "description":
                    "Query resolution step width in duration format or float number of seconds. duration refers to Prometheus duration strings of the form [0-9]+[smhdwy]. For example, 5m refers to a duration of 5 minutes. Defaults to a dynamic value based on start and end. Only applies to query types which produce a matrix response.",
                },
                "interval": {
                    "type":
                    "string",
                    "description":
                    "Only return entries at (or greater than) the specified interval, can be a duration format or float number of seconds. Only applies to queries which produce a stream response. Not to be confused with step, see the explanation under Step versus interval.",
                },
                "direction": {
                    "type":
                    "string",
                    "description":
                    "Determines the sort order of logs. Supported values are forward or backward. Defaults to backward.",
                },
            },
            "required": ["query"],
            "additionalProperties": False
        }
    }
}

fd_query_jaeger_traces = {
    "type": "function",
    "function": {
        "name": "query_jaeger_traces",
        "description": "get traces from jaeger",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "The service name to query traces for.",
                },
                "operation": {
                    "type": "string",
                    "description":
                    "Filter traces by operation name i.e. GET, POST. To see all traces leave this empty.",
                },
                "start_time": {
                    "type": "integer",
                    "description": "The start time in microseconds to query traces for.",
                },
                "end_time": {
                    "type": "integer",
                    "description": "The end time in microseconds to query traces for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "A limit for the number of traces to return.",
                },
                "error_traces_only": {
                    "type": "boolean",
                    "description": "Return all traces or only error traces.",
                },
            },
            "required": ["service", "start_time", "end_time", "limit"],
            "additionalProperties": False
        }
    }
}
