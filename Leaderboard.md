# Participating in the ITBench Leaderboard

## Prerequisite(s)
1. Podman (or Docker)
   
## Getting Started (for agents based on ITBench-SRE-Agent -- this repository)
1. Follow the instructions [here](https://github.com/itbench-hub/ITBench/blob/main/docs/leaderboard.md) to create an agent record.

2. Verify that an `agent-manifest.json` exists is uploaded to the private repository created as a part of the previous step.

3. Clone your private repository and make note of the absolute path to the `agent-manifest.json` uploaded there-in.

3. Clone this repo and `cd` into it
```bash
git clone git@github.com:IBM/ITBench-SRE-Agent.git  
cd ITBench-SRE-Agent  
```  
  
4. Update the environment variables as recommended in the [README][./README.md]
```bash
cp .env.tmpl .env  
vi .env
```  
  
5. Build sre-agent-harness image by running
```bash
podman build -f sre-agent-harness.Dockerfile -t sre-agent-harness:latest .
```

6. Run the agent harness and the underlying agent by running
```bash
podman run --rm -it --name sre-agent-harness \
    --mount type=bind,src=<ABSOLUTE_PATH_TO_agent-manifest.json>,dst=/tmp/agent-manifest.json \
    --mount type=bind,src=<ABSOLUTE_PATH_TO_THE_DOT_ENV>/.env,dst=/etc/lumyn/.env \
    localhost/sre-agent-harness:latest \
    --host itbench.apps.prod.itbench.res.ibm.com \
    --benchmark_timeout 72000
```

7. The agent harness interacts with the ITBench Leaderboard service. It runs your agent in a containerized environment on your system and once a scenario run is complete transitions to the next.

## Getting Started (for agents independent of ITBench-SRE-Agent -- this repository)

1. Follow the instructions [here](https://github.com/itbench-hub/ITBench/blob/main/docs/leaderboard.md) to create an agent record.

2. Verify that an `agent-manifest.json` exists is uploaded to the private repository created as a part of the previous step.

3. Clone your private repository and make note of the absolute path to the `agent-manifest.json` uploaded there-in.

3. Clone this repo and `cd` into it
```bash
git clone git@github.com:IBM/ITBench-SRE-Agent.git  
cd ITBench-SRE-Agent  
```

4. Update the lines [here](https://github.com/itbench-hub/ITBench-SRE-Agent/blob/main/sre-agent-harness.Dockerfile#L15-L18) to install agent, agent-related dependencies.

5. Tweak the line [here](https://github.com/itbench-hub/ITBench-SRE-Agent/blob/main/agent-harness-sre.yaml#L27) to run your agent or framework.

6. Build/modify your existing agent: The agent harness orchestrates the agent and then makes the following environment variables available to the agent:
```
export KUBECONFIG=${tmpdir}/kubeconfig.yaml
export OBSERVABILITY_STACK_URL=${base_url}
export TOPOLOGY_URL=${base_url}/topology
```
The agent can then use these the following end-points to interact with the observability environment. So for say:  
a. Alerts: `${OBSERVABILITY_STACK_URL}/prometheus/api/v1/alerts` [Reference tool](https://github.com/itbench-hub/ITBench-SRE-Agent/blob/main/src/lumyn/tools/observability_stack/get_alerts.py)  
b. Metrics in Prometheus: `${OBSERVABILITY_STACK_URL}/prometheus/api/v1/query` [Reference tool](https://github.com/itbench-hub/ITBench-SRE-Agent/blob/main/src/lumyn/tools/observability_stack/nl2metrics.py)  
c. Traces in Jaeger: `${OBSERVABILITY_STACK_URL}/jaeger/api/traces` [Reference tool](https://github.com/itbench-hub/ITBench-SRE-Agent/blob/main/src/lumyn/tools/observability_stack/nl2traces.py)  
d. Topology: `${OBSERVABILITY_URL}/topology` [Reference tool](https://github.com/itbench-hub/ITBench-SRE-Agent/blob/main/src/lumyn/tools/observability_stack/get_topology_nodes.py)  

7. Build sre-agent-harness image by running
```bash
podman build -f sre-agent-harness.Dockerfile -t sre-agent-harness:latest .
```

8. Run the agent harness and the underlying agent by running
```bash
podman run --rm -it --name sre-agent-harness \
    --mount type=bind,src=<ABSOLUTE_PATH_TO_agent-manifest.json>,dst=/tmp/agent-manifest.json \
    localhost/sre-agent-harness:latest \
    --host itbench.apps.prod.itbench.res.ibm.com \
    --benchmark_timeout 72000
```

9. The agent harness interacts with the ITBench Leaderboard service. It runs your agent in the containerized environment on your system and once a scenario run is complete transitions to the next.
