FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Update package list and install required dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    sudo \
    curl \
    ca-certificates \
    && apt-get clean

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

# Create user "sre-agent" with UID 1001 and add to sudo group
RUN useradd -m -u 1001 -G sudo -s /bin/bash sre-agent && \
    echo "sre-agent ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Ensure correct permissions for /app directory
RUN mkdir -p /app/lumyn && \
    chgrp -R 0 /app && \
    chmod -R g=u /app

# Install Python dependencies
RUN pip install --no-cache-dir uv
RUN pip install --no-cache-dir crewai
RUN pip install --no-cache-dir crewai-tools
RUN crewai install

# Set working directory for the application
WORKDIR /app/lumyn
COPY . .

# Ensure correct permissions again after copying files
RUN chgrp -R 0 /app && \
    chmod -R g=u /app && \
    chown -R sre-agent:sre-agent /app

# Switch to the "sre-agent" user
USER sre-agent
