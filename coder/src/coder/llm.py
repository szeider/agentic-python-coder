"""LLM configuration for OpenRouter."""

import os
from typing import Optional
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# Default model to use for the agent
MODEL_STRING = "anthropic/claude-sonnet-4"


def get_openrouter_llm(
    model: str = MODEL_STRING, temperature: float = 0.0, api_key: Optional[str] = None
) -> ChatOpenAI:
    """Create an OpenRouter LLM instance.

    Args:
        model: Model identifier (default: anthropic/claude-sonnet-4)
        temperature: Temperature for sampling (default: 0.0)
        api_key: Optional API key (will use env var if not provided)

    Returns:
        Configured ChatOpenAI instance for OpenRouter
    """
    from pathlib import Path

    # If api_key provided, use it directly
    if api_key:
        pass  # Use the provided key
    else:
        # Load from ~/.config/coder/.env
        config_env = Path.home() / ".config" / "coder" / ".env"
        if config_env.exists():
            load_dotenv(dotenv_path=config_env, override=True)

        # Get API key from environment
        api_key = os.getenv("OPENROUTER_API_KEY")

        if not api_key:
            print("⚠️ No API key found. Set up with:")
            print("  mkdir -p ~/.config/coder")
            print("  echo 'OPENROUTER_API_KEY=sk-or-...' > ~/.config/coder/.env")
            print("\nOr use: --api-key sk-or-...")
            raise ValueError("OPENROUTER_API_KEY not configured")

    # Create LLM instance with usage tracking enabled
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=api_key,
        openai_api_base="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/python-coding-agent",
            "X-Title": "Python Coding Agent",
        },
        # Enable OpenRouter usage accounting in streaming mode
        # This adds usage data to the final SSE chunk
        streaming=True,
        model_kwargs={"stream_options": {"include_usage": True}},
    )

    return llm
