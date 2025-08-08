"""LLM configuration for OpenRouter."""

import os
from typing import Optional
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# Default model to use for the agent
MODEL_STRING = "anthropic/claude-sonnet-4"


def get_openrouter_llm(
    model: str = MODEL_STRING,
    temperature: float = 0.0,
    api_key: Optional[str] = None
) -> ChatOpenAI:
    """Create an OpenRouter LLM instance.
    
    Args:
        model: Model identifier (default: anthropic/claude-sonnet-4)
        temperature: Temperature for sampling (default: 0.0)
        api_key: Optional API key (will use env var if not provided)
        
    Returns:
        Configured ChatOpenAI instance for OpenRouter
    """
    # Load environment variables from .env file
    # Search for .env in current directory and parent directories
    from pathlib import Path
    
    # First try to load from current directory
    current = Path.cwd()
    env_loaded = False
    
    # Search up the directory tree for .env file
    for parent in [current] + list(current.parents)[:10]:  # Limit search depth
        env_file = parent / '.env'
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)
            env_loaded = True
            break
    
    # If no .env found, try default load_dotenv which searches in standard locations
    if not env_loaded:
        load_dotenv()
    
    # Get API key
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment variables")
    
    # Create LLM instance with usage tracking enabled
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/python-coding-agent",
            "X-Title": "Python Coding Agent"
        },
        # Enable OpenRouter usage accounting in streaming mode
        # This adds usage data to the final SSE chunk
        streaming=True,
        stream_options={"include_usage": True}
    )
    
    return llm