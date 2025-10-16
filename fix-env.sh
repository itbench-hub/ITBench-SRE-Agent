#!/bin/bash

# Fix the environment variables in .env file to use local paths instead of Docker paths
echo "Fixing environment variables in .env file..."

# Backup the original .env file
cp .env .env.backup

# Update the environment variables to use local paths
sed -i 's|SRE_AGENT_EVALUATION_DIRECTORY="/app/lumyn/outputs"|SRE_AGENT_EVALUATION_DIRECTORY="/home/user/ITBench/ITBench-SRE-Agent/outputs"|g' .env
sed -i 's|STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH="/app/lumyn/outputs"|STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH="/home/user/ITBench/ITBench-SRE-Agent/outputs"|g' .env

echo "Environment variables fixed!"
echo "Updated .env file:"
grep -E "(SRE_AGENT_EVALUATION_DIRECTORY|STRUCTURED_UNSTRUCTURED_OUTPUT_DIRECTORY_PATH)" .env
