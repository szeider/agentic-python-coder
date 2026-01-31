"""LLM configuration for OpenRouter."""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# Default model name (without .json)
DEFAULT_MODEL = "sonnet45"


@dataclass
class LLMConfig:
    """Configuration for an LLM via OpenRouter."""

    client: OpenAI
    model: str  # e.g. "anthropic/claude-sonnet-4.5"
    api_params: dict[str, Any] = field(
        default_factory=dict
    )  # temperature, max_tokens, etc.


def get_api_key() -> str:
    """Get API key from environment or config file.

    Returns:
        API key string

    Raises:
        ValueError: If no API key found
    """
    # Load from ~/.config/coder/.env (don't override shell env vars)
    config_env = Path.home() / ".config" / "coder" / ".env"
    if config_env.exists():
        load_dotenv(dotenv_path=config_env, override=False)

    # Get API key from environment
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        print("Warning: No API key found. Set up with:", file=sys.stderr)
        print("  mkdir -p ~/.config/coder", file=sys.stderr)
        print(
            "  echo 'OPENROUTER_API_KEY=sk-or-...' > ~/.config/coder/.env",
            file=sys.stderr,
        )
        print("\nOr use: --api-key sk-or-...", file=sys.stderr)
        raise ValueError("OPENROUTER_API_KEY not configured")

    return api_key


def _load_json_file(path: Path, model: str) -> dict[str, Any]:
    """Load and validate a model JSON file."""
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in model config '{model}': {e}") from e

    if "path" not in config:
        raise ValueError(f"Model config '{model}' missing required key: 'path'")

    return config


def load_model_config(model: str) -> dict[str, Any]:
    """Load model configuration from JSON file.

    Lookup order:
    1. If model ends with .json, treat as explicit path
    2. Local file: ./{model}.json
    3. Bundled default: <package>/models/{model}.json

    Args:
        model: Model name (e.g., "sonnet45") or path to JSON file

    Returns:
        Model configuration dict

    Raises:
        FileNotFoundError: If model config not found
        ValueError: If JSON is invalid or missing required keys
    """
    # Explicit JSON path
    if model.endswith(".json"):
        path = Path(model).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model config not found: {model}")
        return _load_json_file(path, model)

    # Local override: ./{model}.json
    local_path = Path(f"./{model}.json")
    if local_path.exists():
        return _load_json_file(local_path, model)

    # Bundled default: <package>/models/{model}.json
    package_dir = Path(__file__).parent
    bundled_path = package_dir / "models" / f"{model}.json"
    if bundled_path.exists():
        return _load_json_file(bundled_path, model)

    # List available models for error message
    available = list_available_models()
    raise FileNotFoundError(
        f"Model '{model}' not found. Available: {', '.join(available)}"
    )


def list_available_models() -> list[str]:
    """List all available model names (bundled defaults).

    Returns:
        List of model names (without .json extension)
    """
    package_dir = Path(__file__).parent
    models_dir = package_dir / "models"
    if not models_dir.exists():
        return []
    return sorted(p.stem for p in models_dir.glob("*.json"))


def get_openrouter_llm(
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    verbose: bool = False,
) -> LLMConfig:
    """Create a fully configured LLMConfig for OpenRouter.

    Args:
        model: Model name (e.g., "sonnet45") or path to JSON file
        api_key: Optional API key
        verbose: If True, print model info to console

    Returns:
        LLMConfig with configured OpenAI client

    Raises:
        FileNotFoundError: If model config not found
        ValueError: If API key not configured
    """
    # Load config from JSON
    config = load_model_config(model)
    model_path = config["path"]

    if verbose:
        print(f"Using model: {model_path}")
        if os.getenv("CODER_VERBOSE"):
            for key, value in config.items():
                if key != "path":
                    print(f"   {key}: {value}")

    # Get API key
    if not api_key:
        api_key = get_api_key()

    # Build client kwargs
    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "base_url": "https://openrouter.ai/api/v1",
        "default_headers": {
            "HTTP-Referer": "https://github.com/szeider/agentic-python-coder",
            "X-Title": "Agentic Python Coder",
        },
    }

    # Add request_timeout as client timeout
    if "request_timeout" in config:
        client_kwargs["timeout"] = config["request_timeout"]

    client = OpenAI(**client_kwargs)

    # Build api_params (passed to chat.completions.create)
    api_params: dict[str, Any] = {}

    if config.get("no_sampling_params"):
        # Models like GPT-5 that don't accept sampling parameters
        if "max_tokens" in config:
            api_params["max_tokens"] = config["max_tokens"]
    else:
        # Standard parameters
        for key in (
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
        ):
            if key in config:
                api_params[key] = config[key]
        if "top_k" in config:
            # OpenRouter supports top_k via extra_body
            api_params["extra_body"] = {"top_k": config["top_k"]}

    return LLMConfig(client=client, model=model_path, api_params=api_params)
