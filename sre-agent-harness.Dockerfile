FROM ghcr.io/ibm/itbench-utilities/agent-harness-base:0.0.3 AS base

WORKDIR /etc

# COPY THE AGENT REPO
COPY . ./lumyn
WORKDIR /etc/lumyn

# Install OS-related dependencies
RUN apt-get install -y jq
RUN curl -LO https://dl.k8s.io/release/v1.31.0/bin/linux/$(dpkg --print-architecture)/kubectl && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

# Install Agent-related dependencies
RUN pip install uv
RUN pip install crewai crewai-tools
RUN crewai install

# CREATE OUTPUT DIRECTORY
RUN mkdir -p outputs
RUN mkdir -p outputs/agent_evaluation

# SET OUTPUT DIRECTORY. SHOULD BE THE SAME AS IN AGENT HARNESS
ENV STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH="/etc/lumyn/outputs/agent_evaluation/"

WORKDIR /etc/agent-benchmark

RUN chmod +x /etc/lumyn/entrypoint.sh
ENTRYPOINT ["/etc/lumyn/entrypoint.sh"]
