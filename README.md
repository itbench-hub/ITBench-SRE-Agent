# ITBench SRE Agent

**AI-Powered Site Reliability Engineering Agent**

## Overview

The ITBench SRE Agent is an open-source AI-powered Site Reliability Engineering agent that automates incident response in Kubernetes and OpenShift environments. Leveraging large language models and built on the CrewAI framework, this intelligent agent diagnoses complex system failures, traces root causes, and implements remediation strategies within real-world inspired incident scenarios on the ITBench platform.

### Key Features

- **Automated Incident Response**: Diagnose and resolve incidents in Kubernetes environments
- **Real-world Scenarios**: Works with ITBench's collection of realistic SRE incident scenarios
- **Observability Integration**: Integrates with Prometheus, Jaeger, and, Clickhouse
- **Containerized Execution**: Runs safely in containers to prevent harmful commands on host systems

## Quick Start

### Prerequisites
- [Docker](https://docs.docker.com/get-started/get-docker/)

### Running with Docker
The agent should always be run in a container in order to prevent harmful commands being run on the user's PC.

1. **Clone the repository**
   ```bash
   git clone https://github.com/IBM/ITBench-SRE-Agent
   cd ITBench-SRE-Agent
   ```

2. **Prepare your kubeconfig**
   
   Move the kubeconfig file from the cluster on which the ITBench is running into the root directory of this repo and rename it to `config`:
   ```bash
   mv /path/to/your/kubeconfig ./config
   ```

3. **Configure environment**
   
   Modify the provided `.env.tmpl` as needed and move it to the root directory of this repo and rename it `.env`.

4. **Build the container image**
   ```bash
   docker build -t itbench-sre-agent --no-cache .
   ```

5. **Run the agent**
   ```bash
   # macOS
   docker run --mount type=bind,src="$(pwd)",target=/app/lumyn -e KUBECONFIG=/app/lumyn/config -it itbench-sre-agent /bin/bash
   
   # Linux
   docker run --network=host --mount type=bind,src="$(pwd)",target=/app/lumyn -e KUBECONFIG=/app/lumyn/config -it itbench-sre-agent /bin/bash
   ```

6. **Get the observability URL**
   
   Inside the docker container, run:
   ```bash
   kubectl get ingress -n prometheus
   ```
   
   You should see output like:
   ```
   NAME         CLASS   HOSTS   ADDRESS                                                                   PORTS   AGE
   prometheus   nginx   *       ad54bc930b7ec40c38f06be1a1ed0758-1859094179.us-west-2.elb.amazonaws.com   80      10h
   ```
   
   Copy the content under the `ADDRESS` section. This is your `<observability-url>`.

7. **Update environment variables**
   
   Open the `.env` file in a text editor and update the following values:
   - `API_KEY_AGENTS`: Your provided API key
   - `API_KEY_TOOLS`: Your provided API key  
   - `OBSERVABILITY_STACK_URL`: `http://<observability-url>`
   - `TOPOLOGY_URL`: `http://<observability-url>/topology`

8. **Start the agent**
   ```bash
   crewai run
   ```

## Developer Guide

Please see our [Developer Guide](DEVELOPER.md) for detailed information on:
- Local development setup
- Configuration options
- Customization and extension

## ITBench Ecosystem and Related Repositories

- [ITBench](https://github.com/IBM/ITBench): Central repository providing an overview of the ITBench ecosystem, related announcements, and publications.
- [CISO-CAA Agent](https://github.com/IBM/ITBench-CISO-CAA-Agent): CISO (Chief Information Security Officer) agents that automate compliance assessments by generating policies from natural language, collecting evidence, integrating with GitOps workflows, and deploying policies for assessment.
- [SRE Agent](https://github.com/IBM/ITBench-SRE-Agent): SRE (Site Reliability Engineering) agents designed to diagnose and remediate problems in Kubernetes-based environments. Leverage logs, metrics, traces, and Kubernetes states/events from the IT enviroment.
- [ITBench Leaderboard](https://github.com/IBM/ITBench-Leaderboard): Service that handles scenario deployment, agent evaluation, and maintains a public leaderboard for comparing agent performance on ITOps use cases.
- [ITBench Utilities](https://github.com/IBM/ITBench-Utilities): Collection of supporting tools and utilities for participants in the ITBench ecosystem and leaderboard challenges.
- [ITBench Tutorials](https://github.com/IBM/ITBench-Tutorials): Repository containing the latest tutorials, workshops, and educational content for getting started with ITBench.

## Maintainers

- Noah Zheutlin - [@noahzibm](https://github.com/noahzibm)

### How to Cite

```bibtex
@misc{jha2025itbench,
      title={ITBench: Evaluating AI Agents across Diverse Real-World IT Automation Tasks},
      author={Jha, Saurabh and Arora, Rohan and Watanabe, Yuji and others},
      year={2025},
      url={https://github.com/IBM/itbench-sample-scenarios/blob/main/it_bench_arxiv.pdf}
}
```
