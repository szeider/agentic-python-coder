"""Python Coding Agent - A minimal coding assistant using LangGraph and OpenRouter."""

__version__ = "2.0.0"

# High-level API (recommended for most users)
from agentic_python_coder.runner import solve_task

# Lower-level API (for custom workflows)
from agentic_python_coder.agent import (
    create_coding_agent,
    run_agent,
    get_final_response,
    DEFAULT_STEP_LIMIT,
)

# LLM utilities
from agentic_python_coder.llm import get_openrouter_llm, MODEL_REGISTRY, MODEL_STRING

__all__ = [
    # Version
    "__version__",
    # High-level
    "solve_task",
    # Low-level
    "create_coding_agent",
    "run_agent",
    "get_final_response",
    "DEFAULT_STEP_LIMIT",
    # LLM
    "get_openrouter_llm",
    "MODEL_REGISTRY",
    "MODEL_STRING",
]
