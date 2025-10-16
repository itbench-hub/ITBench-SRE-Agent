# Developer & Contributors Guide

Welcome to the ITBench SRE Agent development guide! This document provides comprehensive information for developers who want to contribute to, customize, or extend the ITBench SRE Agent.

## Prerequisites

### Required Software

- **[Python 3.12](https://www.python.org/downloads/)**
- **[Docker](https://docs.docker.com/get-started/get-docker/)**
- **[Kubernetes cluster](https://kubernetes.io/)** with ITBench scenarios deployed. Please see intructions [here](https://github.com/IBM/ITBench-Scenarios/tree/main/sre).
- **LLM API access** (OpenAI, Azure OpenAI, IBM watsonx, Anthropic, etc.)

### Optional Software

- **[Helm](https://helm.sh/docs/intro/install/)** (v3.16+) - for ITBench scenario deployment

### Installing Prerequisites

#### macOS (using Homebrew)
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required software
brew install python@3.12
brew install docker
brew install helm
brew install kubectl
```

#### Linux (RHEL/CentOS)
```bash
# Install Python 3.12
sudo dnf install python3.12

# Install Docker
sudo dnf install docker
sudo systemctl start docker
sudo systemctl enable docker

# Install Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install kubectl
sudo dnf install kubectl
```

#### Windows
```powershell
# Install Python 3.12 from python.org
# Install Docker Desktop from docker.com
# Install kubectl using chocolatey
choco install kubernetes-cli

# Install Helm
choco install kubernetes-helm
```

## Local Development Setup

### 1. Clone and Setup Repository

```bash
git clone https://github.com/IBM/ITBench-SRE-Agent
cd ITBench-SRE-Agent
```

### 2. Install UV Package Manager

UV is a fast Python package manager that we use for dependency management:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. Install CrewAI

```bash
uv tool install crewai
```

### 4. Install Project Dependencies

```bash
crewai install
```

### 5. Setup Environment Configuration

```bash
cp .env.tmpl .env
# Edit .env with your specific configuration (see Configuration section below)
```

## Configuration

### Environment Variables (.env)

Create a comprehensive `.env` file based on `.env.tmpl`:

#### LLM Configuration for Agents
```bash
# Primary agent model settings
PROVIDER_AGENTS=""           # e.g., watsonx, azure, anthropic, openai
MODEL_AGENTS=""             # e.g., gpt-4o, claude-3-sonnet, ibm/granite-3-2-8b-instruct
URL_AGENTS=""               # API endpoint (not required for OpenAI)
API_VERSION_AGENTS=""       # API version (Azure only, e.g., 2024-12-01-preview)
API_KEY_AGENTS=""           # Your API key
REASONING_EFFORT_AGENTS=""  # For o1/o3 models: low, medium, high
SEED_AGENTS=10              # Sets the seed for reproducibility
TOP_P_AGENTS=0.95           # Top-p sampling parameter
TEMPERATURE_AGENTS=0.0      # Temperature setting (0.0 for deterministic)
THINKING_AGENTS=""          # For Claude Sonnet 3.7 (anthropic) and Granite 3.2 (wx)
THINKING_BUDGET_AGENTS=6000 # For Claude Sonnet 3.7 only (thinking tokens allowed)
MAX_TOKENS_AGENTS=16000     # Maximum tokens per call
```

#### LLM Configuration for Tools
```bash
# Tool model settings (can be same as agents or different)
PROVIDER_TOOLS=""
MODEL_TOOLS=""
URL_TOOLS=""
API_VERSION_TOOLS=""
API_KEY_TOOLS=""
REASONING_EFFORT_TOOLS=""
SEED_TOOLS=10
TOP_P_TOOLS=0.95
TEMPERATURE_TOOLS=0.0
THINKING_TOOLS=""
THINKING_BUDGET_TOOLS=6000
MAX_TOKENS_TOOLS=16000
```

#### Observability Stack Configuration
```bash
# ITBench observability endpoints
OBSERVABILITY_STACK_URL="http://localhost:8080"
TOPOLOGY_URL="http://localhost:8080/topology"
OBSERVABILITY_STACK_SERVICE_ACCOUNT_TOKEN="not_required"
```

#### Optional: Embedding Models (for CrewAI Memory)
```bash
# Embedding configuration for enhanced memory features
MODEL_EMBEDDING=""          # e.g., text-embedding-3-large
URL_EMBEDDING=""            # Embedding API endpoint
API_VERSION_EMBEDDING=""    # API version (e.g., 2023-05-15)
```

#### Watsonx-Specific Configuration
```bash
# Required only when using IBM Watsonx models
WX_PROJECT_ID=""            # Your Watsonx project ID
```

#### System Configuration (DO NOT ALTER)
```bash
AGENT_TASK_DIRECTORY="config"
SRE_AGENT_EVALUATION_DIRECTORY="/app/lumyn/outputs"
STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH="/app/lumyn/outputs"
SRE_AGENT_NAME_VERSION_NUMBER="Test"
EXP_NAME="Test"
GOD_MODE="True"
KUBECONFIG="/app/lumyn/config"
```

### Supported LLM Providers

The agent supports all providers available through [LiteLLM](https://docs.litellm.ai/docs/providers):

## Development Workflow

### Running the Agent Locally

1. **Ensure ITBench scenario is deployed** (see ITBench Integration section)

2. **Start the agent**:
   ```bash
   crewai run
   ```

3. **Monitor outputs** in the console and check `/app/lumyn/outputs` for results

### Using Container Development

For safer development:

1. **Build development image**:
   ```bash
   docker build -t itbench-sre-agent-dev .
   ```

2. **Run with mounted source code**:
   ```bash
   docker run --mount type=bind,src="$(pwd)",target=/app/lumyn \
              -e KUBECONFIG=/app/lumyn/config \
              -it itbench-sre-agent-dev /bin/bash
   ```

## User Interface (UI) interactions for the ITBench SRE-Agent

### Panel UI

The Panel UI provides an interactive web interface:

```bash
cd ui
pip install panel
panel serve panel_main.py --show
```

Navigate to http://localhost:5006/panel_main

### Streamlit UI

Alternative Streamlit interface:

```bash
cd ui
pip install streamlit
streamlit run streamlit_main.py
```

Navigate to http://localhost:8501

## Customization and Extension

### Agent Configuration

#### Modifying Agents (`src/lumyn/config/agents.yaml`)
#### Modifying / Defining Tasks (`src/lumyn/config/tasks.yaml`)
#### Custom Logic (`src/lumyn/crew.py`)
#### Custom Inputs (`src/lumyn/main.py`)
