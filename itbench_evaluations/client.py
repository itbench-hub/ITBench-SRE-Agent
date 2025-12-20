"""OpenAI-compatible client for judge LLM."""

import os
from openai import OpenAI


def create_judge_client() -> OpenAI:
    """Create OpenAI client from environment variables.
    
    Environment variables:
        JUDGE_BASE_URL: Base URL for OpenAI-compatible API
        JUDGE_API_KEY: API key (defaults to "dummy" for local endpoints)
    
    Returns:
        OpenAI client configured for the judge LLM
    """
    base_url = os.environ.get("JUDGE_BASE_URL")
    api_key = os.environ.get("JUDGE_API_KEY", "dummy")
    
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
    )


def get_judge_model() -> str:
    """Get judge model name from environment.
    
    Environment variables:
        JUDGE_MODEL: Model name to use (defaults to "gpt-4-turbo")
    
    Returns:
        Model name string
    """
    return os.environ.get("JUDGE_MODEL", "gpt-4-turbo")
