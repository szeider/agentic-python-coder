"""Python Coding Agent - A minimal coding assistant using LangGraph and OpenRouter."""

__version__ = "2.3.0"

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
from agentic_python_coder.llm import (
    get_openrouter_llm,
    load_model_config,
    list_available_models,
    DEFAULT_MODEL,
)

# Kernel management (multi-kernel API)
from agentic_python_coder.kernel import (
    # Core functions
    create_kernel,
    execute_in_kernel,
    shutdown_kernel_by_id,
    interrupt_kernel_by_id,
    restart_kernel,
    # Query functions
    list_kernels,
    kernel_exists,
    get_kernel_info,
    shutdown_all_kernels,
    # Backward compat
    get_kernel,
    shutdown_kernel,
    # Constants
    DEFAULT_KERNEL_ID,
    MAX_KERNELS,
)

__all__ = [
    # Version
    "__version__",
    # High-level
    "solve_task",
    # Low-level agent
    "create_coding_agent",
    "run_agent",
    "get_final_response",
    "DEFAULT_STEP_LIMIT",
    # LLM
    "get_openrouter_llm",
    "load_model_config",
    "list_available_models",
    "DEFAULT_MODEL",
    # Kernel management
    "create_kernel",
    "execute_in_kernel",
    "shutdown_kernel_by_id",
    "interrupt_kernel_by_id",
    "restart_kernel",
    "list_kernels",
    "kernel_exists",
    "get_kernel_info",
    "shutdown_all_kernels",
    "get_kernel",
    "shutdown_kernel",
    "DEFAULT_KERNEL_ID",
    "MAX_KERNELS",
]
