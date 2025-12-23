"""Tools for the Python coding agent."""

import json
from pathlib import Path
from typing import List, Dict, Any
from langchain_core.tools import tool

from .kernel import get_kernel, format_output


class WorkingDirectory:
    """Manages the working directory for all file operations."""

    _instance = None
    _working_dir = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set(self, path: str):
        """Set the working directory."""
        self._working_dir = Path(path).resolve()
        if not self._working_dir.exists():
            raise ValueError(f"Directory does not exist: {path}")

    def get(self) -> Path:
        """Get the working directory."""
        if self._working_dir is None:
            raise RuntimeError("Working directory not set")
        return self._working_dir

    def resolve_path(self, file_path: str) -> Path:
        """Resolve a path relative to the working directory."""
        path = Path(file_path)
        if path.is_absolute():
            raise ValueError("Absolute paths not allowed")

        full_path = (self.get() / path).resolve()

        # Security check: ensure path is within working directory
        try:
            full_path.relative_to(self.get())
        except ValueError:
            raise ValueError(f"Path {file_path} is outside working directory")

        return full_path


# Global working directory instance
working_dir = WorkingDirectory()


# Helper functions for consistent JSON responses
def success_response(result: Any = None, **kwargs) -> str:
    """Create a success JSON response."""
    response = {"success": True}
    if result is not None:
        response["result"] = result
    response.update(kwargs)
    return json.dumps(response, indent=2)


def error_response(error: str, **kwargs) -> str:
    """Create an error JSON response."""
    response = {"success": False, "error": error}
    response.update(kwargs)
    return json.dumps(response, indent=2)


# Todo management tools
_todos = []


@tool
def todo_write(todos: List[Dict[str, Any]]) -> str:
    """Replace the entire task list with validation.

    Each task should have:
    - id: unique identifier
    - content: task description
    - status: 'pending', 'in_progress', or 'completed'
    - priority: 'high', 'medium', or 'low'

    Args:
        todos: New list of todo items

    Returns:
        JSON with success status and count
    """
    try:
        # Validate only one in_progress
        in_progress = sum(1 for t in todos if t.get("status") == "in_progress")
        if in_progress > 1:
            return error_response("Only one task can be in_progress at a time")

        # Basic validation of required fields
        for todo in todos:
            if not all(key in todo for key in ["id", "content", "status", "priority"]):
                return error_response(
                    "Each todo must have id, content, status, and priority"
                )
            if todo["status"] not in ["pending", "in_progress", "completed"]:
                return error_response(f"Invalid status: {todo['status']}")
            if todo["priority"] not in ["high", "medium", "low"]:
                return error_response(f"Invalid priority: {todo['priority']}")

        global _todos
        _todos = todos
        return success_response(f"Updated {len(todos)} todos", count=len(todos))
    except Exception as e:
        return error_response(f"Error updating todos: {str(e)}")


# Python execution tool
@tool
def python_exec(code: str) -> str:
    """Execute Python code in a persistent IPython kernel.

    IMPORTANT: The kernel maintains state between executions!
    - Variables, functions, and imports persist across calls
    - Use print() to see output, or the last expression will be returned
    - The kernel runs in the working directory context

    Example:
        First call:  x = 5
        Second call: print(x)  # Returns: {"success": true, "stdout": "5"}

        First call:  def add(a, b): return a + b
        Second call: add(3, 4)  # Returns: {"success": true, "result": "7"}

    The code executes in the working directory context, so you can read/write files
    using relative paths.

    Args:
        code: Python code to execute. Multi-line code is supported.

    Returns:
        JSON string with execution results:
        - success: boolean indicating if execution succeeded
        - stdout: captured print output (if any)
        - result: the last expression's value (if any)
        - stderr: warnings (if any)
        - error: error message (if execution failed)
    """
    # Check if we're in dynamic package mode
    import os

    with_packages = None
    if "CODER_WITH_PACKAGES" in os.environ:
        packages_str = os.environ["CODER_WITH_PACKAGES"]
        with_packages = packages_str.split(",") if packages_str else []

    try:
        # Get the persistent kernel with the working directory
        kernel = get_kernel(cwd=str(working_dir.get()), with_packages=with_packages)

        # Execute the user's code
        output = kernel.execute(code)

        # Format and return the output
        return format_output(output)

    except RuntimeError as e:
        # Kernel startup failed - return user-friendly error
        error_msg = str(e)
        if "UV is required" in error_msg:
            return error_response(
                "UV is not installed. To use dynamic package mode, install UV with:\n"
                "curl -LsSf https://astral.sh/uv/install.sh | sh"
            )
        elif "Failed to start kernel" in error_msg:
            return error_response(f"Failed to start Python kernel: {error_msg}")
        else:
            return error_response(f"Kernel error: {error_msg}")

    except Exception as e:
        # Unexpected error
        return error_response(f"Unexpected error executing code: {str(e)}")


# Fileless mode tools
_task_basename = None


def set_task_basename(basename: str):
    """Set the basename for file naming in fileless mode."""
    global _task_basename
    _task_basename = basename


@tool
def save_code(code: str) -> str:
    """Save the final code (fileless mode).

    This saves your code to {basename}_code.py where basename
    is determined from the task file name, or solution.py for inline tasks.

    Args:
        code: The complete Python code

    Returns:
        JSON with success status and file path
    """
    try:
        global _task_basename

        # Determine output filename
        if _task_basename:
            filename = f"{_task_basename}_code.py"
        else:
            filename = "solution.py"

        # Save to working directory
        output_path = working_dir.get() / filename
        output_path.write_text(code)

        return success_response(f"Code saved to {filename}", file_path=str(filename))
    except Exception as e:
        return error_response(f"Error saving code: {str(e)}")


def reset_global_state():
    """Reset all global state to avoid accumulation across runs.

    Called by create_coding_agent() to ensure clean state for each new agent.
    """
    global _todos, _task_basename
    _todos = []
    _task_basename = None
