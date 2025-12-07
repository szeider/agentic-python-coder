"""LLM configuration for OpenRouter."""

import os
from typing import Optional
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from pathlib import Path

# Model aliases to full OpenRouter paths
MODEL_REGISTRY = {
    "deepseek": "deepseek/deepseek-chat-v3.1",
    "sonnet": "anthropic/claude-sonnet-4.5",
    "opus": "anthropic/claude-opus-4.5",
    "default": "anthropic/claude-sonnet-4.5",
    "grok": "x-ai/grok-4.1-fast",
    "qwen": "qwen/qwen3-coder",
    "gemini": "google/gemini-2.5-pro",
    "gpt": "openai/gpt-5",
}

# Model-specific configurations
MODEL_CONFIGS = {
    "deepseek/deepseek-chat-v3.1": {
        "temperature": 0.2,  # Low for deterministic code generation with tool calls
        "max_tokens": 8192,  # Beta API supports up to 8192
        "streaming": True,
        "context_window": 128000,  # Full context window
        "top_p": 1.0,  # Keep at 1.0 with low temperature
        "frequency_penalty": 0,  # Don't use for coding
        "presence_penalty": 0,  # Don't use for coding
        "model_kwargs": {
            "stream_options": {"include_usage": True},
        },
    },
    "anthropic/claude-sonnet-4.5": {
        "temperature": 0.0,  # Default for deterministic output
        "streaming": True,
        "max_tokens": 16384,  # Sonnet 4.5 supports up to 64K
        "model_kwargs": {"stream_options": {"include_usage": True}},
    },
    "anthropic/claude-opus-4.5": {
        "temperature": 0.0,
        "streaming": True,
        "max_tokens": 16384,  # Opus 4.5 supports up to 32K output
        "model_kwargs": {"stream_options": {"include_usage": True}},
    },
    # Other model configurations
    "x-ai/grok-code-fast-1": {
        "temperature": 0.15,
        "max_tokens": 2000,
        "streaming": True,
        "context_window": 256000,
        "top_p": 0.9,
        # Note: Grok doesn't accept frequency_penalty or presence_penalty
        "model_kwargs": {
            "stream_options": {"include_usage": True}
            # Reasoning mode may be added later when supported
        },
    },
    "qwen/qwen3-coder": {
        "temperature": 0.15,
        "max_tokens": 2048,
        "streaming": True,
        "context_window": 256000,
        "top_p": 0.9,
        "model_kwargs": {
            "stream_options": {"include_usage": True}
            # Provider filtering would be added via headers if needed
        },
    },
    "google/gemini-2.5-pro": {
        "temperature": 0.3,
        "max_tokens": 2048,  # Will be mapped to max_output_tokens
        "streaming": True,
        "context_window": 1048576,
        "top_p": 0.9,
        # Note: No top_k or set to 64 (Google's fixed value)
        "request_timeout": 60,  # Handle slow responses on free tier
        "model_kwargs": {"stream_options": {"include_usage": True}},
    },
    "openai/gpt-5": {
        # NO temperature, top_p, or penalty parameters for GPT-5
        "max_tokens": 3000,
        "streaming": True,
        "context_window": 400000,
        "model_kwargs": {
            "stream_options": {"include_usage": True},
            "parallel_tool_calls": False,
            # Additional parameters can be added when supported
        },
    },
}

# Default configuration for unknown models
DEFAULT_CONFIG = {
    "temperature": 0.0,
    "max_tokens": 4096,
    "streaming": True,
    "context_window": 32000,
    "model_kwargs": {"stream_options": {"include_usage": True}},
}

# Keep old constant for backward compatibility
MODEL_STRING = "anthropic/claude-sonnet-4.5"


def get_api_key() -> str:
    """Get API key from environment or config file.

    Returns:
        API key string

    Raises:
        ValueError: If no API key found
    """
    # Load from ~/.config/coder/.env
    config_env = Path.home() / ".config" / "coder" / ".env"
    if config_env.exists():
        load_dotenv(dotenv_path=config_env, override=True)

    # Get API key from environment
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        print("Warning: No API key found. Set up with:")
        print("  mkdir -p ~/.config/coder")
        print("  echo 'OPENROUTER_API_KEY=sk-or-...' > ~/.config/coder/.env")
        print("\nOr use: --api-key sk-or-...")
        raise ValueError("OPENROUTER_API_KEY not configured")

    return api_key


def get_openrouter_llm(
    model: str = "default",
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    verbose: bool = False,
) -> ChatOpenAI:
    """Create a fully configured OpenRouter LLM instance.
    Special handling for GPT-5 which doesn't accept sampling parameters.

    Args:
        model: Model alias (e.g., "deepseek", "claude") or full path
        temperature: Optional temperature override
        api_key: Optional API key
        verbose: If True, print model info to console (default False for library use)

    Returns:
        Fully configured ChatOpenAI instance

    Raises:
        ValueError: If model alias is not recognized
    """
    # Handle direct model path (backward compatibility)
    if "/" in model:
        model_path = model
        # Get config for this path or use default
        config = MODEL_CONFIGS.get(model_path, DEFAULT_CONFIG.copy())
    else:
        # Resolve alias to full path
        if model not in MODEL_REGISTRY:
            available = ", ".join(sorted(MODEL_REGISTRY.keys()))
            raise ValueError(f"Unknown model: '{model}'. Available models: {available}")

        model_path = MODEL_REGISTRY[model]

        # Get hardcoded config for this model
        config = MODEL_CONFIGS.get(model_path, DEFAULT_CONFIG.copy())

    # Print model info only if verbose
    if verbose and model != "default":
        print(f"Using model: {model_path}")
        if os.getenv("CODER_VERBOSE"):
            # Special handling for GPT-5 which has no temperature
            if model_path == "openai/gpt-5":
                print(f"   Max tokens: {config.get('max_tokens', 'default')}")
                print(f"   Streaming: {config['streaming']}")
            else:
                print(f"   Temperature: {config.get('temperature', 'default')}")
                print(f"   Max tokens: {config.get('max_tokens', 'default')}")
                print(f"   Streaming: {config['streaming']}")

    # Get API key
    if not api_key:
        api_key = get_api_key()

    # Create base kwargs
    llm_kwargs = {
        "model": model_path,
        "openai_api_key": api_key,
        "openai_api_base": "https://openrouter.ai/api/v1",
        "default_headers": {
            "HTTP-Referer": "https://github.com/szeider/agentic-python-coder",
            "X-Title": "Agentic Python Coder",
        },
        "streaming": config["streaming"],
        "model_kwargs": config.get("model_kwargs", {}),
    }

    # Special case for GPT-5: NO sampling parameters
    if model_path == "openai/gpt-5":
        # Only add max_tokens for GPT-5
        if "max_tokens" in config:
            llm_kwargs["max_tokens"] = config["max_tokens"]
    else:
        # All other models get standard parameters
        llm_kwargs["temperature"] = config.get("temperature", 0.0)
        if temperature is not None:  # Allow override
            llm_kwargs["temperature"] = temperature

        # Add optional parameters
        if "max_tokens" in config:
            llm_kwargs["max_tokens"] = config["max_tokens"]
        if "top_p" in config:
            llm_kwargs["top_p"] = config["top_p"]
        if "top_k" in config:
            llm_kwargs["top_k"] = config["top_k"]
        if "frequency_penalty" in config:
            llm_kwargs["frequency_penalty"] = config["frequency_penalty"]
        if "presence_penalty" in config:
            llm_kwargs["presence_penalty"] = config["presence_penalty"]

    # Add request_timeout for models that need it (e.g., Gemini)
    if "request_timeout" in config:
        llm_kwargs["request_timeout"] = config["request_timeout"]

    llm = ChatOpenAI(**llm_kwargs)

    return llm
