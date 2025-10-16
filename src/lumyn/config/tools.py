# Tool and Tool Input Descriptions
NL2KubectlCustomToolInputPrompt="NL query to execute. Keep queries simple and straight-forward. This tool cannot handle complex mutli-step queries. Make sure to include a namespace where required."
NL2KubectlCustomToolPrompt="Converts natural language queries into **kubectl** commands and executes them to retrieve details about Kubernetes components (e.g., deployments, services, pods). **Only supports simple, single-step queries. Most kubectl queries require a namespace. Do not use commands that will create an interactive shell"
NL2TracesCustomToolInputPrompt="Natural language query to be converted to function arguments."
NL2TracesCustomToolPrompt="Take in a natural language query or utterance and turn it into function arguments. This tool is for gathering traces from jaeger. When using NL2Traces Tool you could ask queries like: retrieve traces for payment-service for the last hour get traces for test-service for the last 15 minutes get GET traces for back-service for the last 15 minutes get POST traces from ticket-service for the last 5 minutes get POST traces from <service-name> for the last X minutes"
NL2MetricsCustomToolInputPrompt="PromQL query to execute."
NL2MetricsCustomToolPrompt="Generates and executes PromQL queries to retrieve metrics from Prometheus via the Grafana API. Use this tool to query resource usage metrics (CPU, memory, network, etc.) for specific Kubernetes entities. Example queries:'Get the average CPU usage of `pod-456` in namespace `complex-us` over the last hour.', 'Retrieve the network received bytes for `pod-789` in namespace `simple-us` over the last 10 minutes.', 'Fetch the total memory utilization of deployment `front` in namespace `simple-us` currently.'"
NL2LogsCustomToolInputPrompt="NL query to execute."
NL2LogsCustomToolPrompt="Converts natural language to LogQL queries and executes them to access logs (and other information) from Loki via the Grafana API. When using the NL2Logs Tool you could ask queries like: get the logs from the payment deployment get the logs from the worker-node-1 kubernetes host get the logs from the payment service with label app=payment NL2Logs only works for logs from services using their app name."

# ICL
NL2KubectlICL="""
EXAMPLE INPUTS AND OUTPUTS

THESE EXAMPLES ARE FOR DIAGNOSIS

INPUT: Get the yaml file for the deployment called back in the default namespace.
OUTPUT: ```bash\nkubectl get deployment back -o yaml\n```

INPUT: Get the logs from the pod 123xyz in the complexdd namespace.
OUTPUT: ```bash\nkubectl logs 123xyz -n complexdd\n```

INPUT: get all the services in the abc789 namespace
OUTPUT: ```bash\nkubectl get services -n abc789\n```

INPUT: describe the pod lol123 in the abc789 namespace
OUTPUT: ```bash\nkubectl describe pod lol123 -n abc789\n```

INPUT: Get the events related to the deployment "my-deployment" in the "production" namespace.
OUTPUT: ```bash\nkubectl get events -n production --field-selector metadata.name=my-deployment\n```

THESE EXAMPLES ARE FOR REMEDIATION

INPUT: Execute the command `ls -l` in the container named "web" of the pod "my-pod" in the "staging" namespace.
OUTPUT: ```bash\nkubectl exec -it -n staging my-pod -c web -- ls -l\n```

INPUT: Delete the pod named "crashing-pod" in the "production" namespace, forcing Kubernetes to recreate it.
OUTPUT: ```bash\nkubectl delete pod crashing-pod -n production --force --grace-period=0\n```

INPUT: Edit the deployment "my-app" in the "staging" namespace to increase the resource limits for the container "main" to 2 CPUs and 4Gi of memory.
OUTPUT: ```bash\nkubectl edit deployment/my-app -n staging  # Then manually edit the resource limits in the editor\n```

INPUT: Patch the deployment "frontend-api" in the "production" namespace to update the image of the container named "api-container" to "api-image:2.0" to fix a bug.
OUTPUT: kubectl patch deployment/frontend-api -n production --type='json' -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/image", "value":"api-image:2.0"}]'

INPUT: Patch the deployment "data-processor" in the "data" namespace to increase the CPU request for the container named "processor" to "500m" to ensure it has more guaranteed CPU resources.
OUTPUT: kubectl patch deployment/data-processor -n data --patch '{"spec": {"template": {"spec": {"containers": [{"name": "processor", "resources": {"requests": {"cpu": "500m"}}}]}}}}'

END OF EXAMPLES
"""
NL2TracesICL="""
EXAMPLE INPUTS AND OUTPUTS

INPUT: Provide the correct tool call for this action: Retrieve traces for front-service for the last 15 minutes. The current time in microseconds is 1727262221573511
OUTPUT: {service: front-service, start_time: 1727261321573511, end_time: 1727262221573511, limit: 1}

INPUT: Provide the correct tool call for this action: Get traces for back-service for the last 15 minutes. The current time in microseconds is 1727262221573511
OUTPUT: {service: back-service, start_time: 1727261321573511, end_time: 1727262221573511, limit: 1}

INPUT: Provide the correct tool call for this action: Get GET traces for back-service for the last 15 minutes. The current time in microseconds is 1727262221573511
OUTPUT: {service: back-service, operation: GET, start_time: 1727261321573511, end_time: 1727262221573511, limit: 1}

INPUT: retrieve traces for frontend service in hotel-reservations namespace for the last hour. The current time in microseconds is 1732066095076488
OUTPUT: {service: 'frontend', 'start_time': 1732062495076488, 'end_time': 1732066095076488, 'limit': 1}

END OF EXAMPLES
"""
NL2MetricsICL="""
EXAMPLE INPUTS AND OUTPUTS

INPUT: get the memory utilization of a pod-123 in namespace simple-us
OUTPUT: ```promql\nsum(container_memory_usage_bytes{image!='',container!='',pod="pod-123",namespace="simple-us"})\n```

INPUT: get the requests of a pod-123 in namespace simple-us
OUTPUT: ```promql\navg(kube_pod_container_resource_requests{resource='cpu', pod='pod-123', namespace='simple-us'})\n```

INPUT: get the limits of a pod-123 in namespace simple-us
OUTPUT: ```promql\navg(kube_pod_container_resource_limits{resource='cpu', pod='pod-123', namespace='simple-us'})\n```

INPUT: get the memory utilization by a deployment front in namespace simple-us
OUTPUT: ```promql\nsum(rate(container_memory_usage_bytes{namespace="simple-us", pod=~"front-.*"}[5m])) by (namespace) / sum(kube_pod_container_resource_limits{namespace="simple-us", resource="memory", pod=~"front-.*"}) by (namespace)\n```

INPUT: get the throttle ratio for a deployment front in namespace simple-us
OUTPUT: ```promql\n(sum(increase(container_cpu_cfs_throttled_periods_total{namespace="simple-us", container=~"front.*"}[5m])) by (namespace) / sum(increase(container_cpu_cfs_periods_total{namespace="simple-us", container=~"front.*"}[5m])) by (namespace))\n```

INPUT: get the CPU usage of a pod-456 in namespace complex-us
OUTPUT: ```promql\nsum(rate(container_cpu_usage_seconds_total{pod="pod-456", namespace="complex-us"}[5m]))\n```

INPUT: get the memory usage of a node-789
OUTPUT: ```promql\nsum(node_memory_MemTotal_bytes{node="node-789"}) - sum(node_memory_MemAvailable_bytes{node="node-789"})\n```

INPUT: get the network received bytes of a pod-789 in namespace simple-us
OUTPUT: ```promql\nrate(container_network_receive_bytes_total{pod="pod-789", namespace="simple-us"}[5m])\n```

END OF EXAMPLES
"""
NL2LogsICL="""
#THIS NEEDS TO BE UPDATED TO THE FULL FUNCTION CALL INSTEAD OF JUST THE LOGQL QUERY

EXAMPLE INPUTS AND OUTPUTS

INPUT: get the logs from <value> <app>
OUTPUT: {<label>=<value>}

INPUT: get the logs from the payment service with label app=payment
OUTPUT: {app="payment"}

INPUT: get the logs from the payment deployment in the default namespace
OUTPUT: {container=~"payment-*"}

INPUT: get the logs from the worker-node-1 kubernetes host
OUTPUT: {node_name="worker-node-1"}

INPUT: get the kubernetes events for a deployment with the label app=back in the default namespace
OUTPUT: {source="kubernetes-event-exporter"} |= `"app":"back"` |= `"namespace":"default"`

INPUT: get all events from deployment back in namespace simple-us
OUTPUT: {source="kubernetes-event-exporter"} |= `"namespace":"simple-us"` |= `"kind":"Deployment"` |= `"name":"back"`

END OF EXAMPLES
"""

# Tool System Prompts
NL2KubectlSystemPrompt="You write kubectl commands. Answer with only the correct kubectl command."
NL2TracesSystemPrompt="You are a function calling bot. You are given a prompt and you need to generate a tool call based on the prompt. Make sure to fill the parameters correctly. If no timeframe is given always get the last 10 minutes of traces."
NL2MetricsSystemPrompt="You write PromQL queries. Answer with only the correct PromQL query. The formatting should always be like this: ```promql\n<promql query>\n```"
NL2LogsSystemPrompt="Provide the correct tool call for querying loki logs using parameters provided in the input. For the LogQL query generate it using the input as instructions. Do not wrap the LogQL query in any tags or special formatting."

# Tool Prompts
NL2KubectlPrompt=f"{NL2KubectlICL}\n\nThe formatting should always be like this: ```bash\n<kubectl command>\n``` Convert this query into a kubectl command: "
NL2TracesPrompt=f"{NL2TracesICL}\n\nProvide the correct tool call for this action: "
NL2MetricsPrompt=f"{NL2MetricsICL}\n\nWrite a PromQL query to do the following: "
NL2LogsPrompt=f"{NL2LogsICL}\n\nWrite a LogQL query to do the following and return it in a tool call to query_loki_logs: "