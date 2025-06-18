FROM agent-harness:latest

WORKDIR /app

# COPY THE AGENT REPO
COPY . ./lumyn
WORKDIR /app/lumyn

# INSTALL AGENT DEPENDENCIES
RUN pip install uv
RUN pip install crewai crewai-tools
RUN crewai install
RUN curl -LO https://dl.k8s.io/release/v1.31.0/bin/linux/$(dpkg --print-architecture)/kubectl && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

# CREATE OUTPUT DIRECTORY
RUN mkdir -p outputs
RUN mkdir -p outputs/agent_evaluation

# SET OUTPUT DIRECTORY. SHOULD BE THE SAME AS IN AGENT HARNESS
ENV STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH="/app/lumyn/outputs/agent_evaluation/"

WORKDIR /app/agent-benchmark
