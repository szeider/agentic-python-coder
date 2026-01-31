"""Tools for the Python coding agent."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Callable

from .kernel import get_kernel, format_output


@dataclass
class Tool:
    """A tool that the agent can use."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for parameters
    function: Callable[..., Any]

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return result as string.

        Functions already return JSON strings, so pass through verbatim.
        """
        return self.function(**kwargs)


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI format."""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


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


# Todo management
_todos = []


def todo_write(todos: List[Dict[str, Any]]) -> str:
    """Replace the entire task list with validation.

    Each task should have:
    - id: unique identifier
    - content: task description
    - status: 'pending', 'in_progress', or 'completed'
    - priority: 'high', 'medium', or 'low'
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


# Python execution
def python_exec(code: str) -> str:
    """Execute Python code in a persistent IPython kernel."""
    import os

    with_packages = None
    if "CODER_WITH_PACKAGES" in os.environ:
        packages_str = os.environ["CODER_WITH_PACKAGES"]
        with_packages = packages_str.split(",") if packages_str else []

    try:
        kernel = get_kernel(cwd=str(working_dir.get()), with_packages=with_packages)
        output = kernel.execute(code)
        return format_output(output)

    except RuntimeError as e:
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
        return error_response(f"Unexpected error executing code: {str(e)}")


# File saving
_task_basename = None


def set_task_basename(basename: str):
    """Set the basename for file naming in fileless mode."""
    global _task_basename
    _task_basename = basename


def save_code(code: str) -> str:
    """Save the final code (fileless mode)."""
    try:
        global _task_basename

        if _task_basename:
            filename = f"{_task_basename}_code.py"
        else:
            filename = "solution.py"

        output_path = working_dir.get() / filename
        output_path.write_text(code)

        return success_response(f"Code saved to {filename}", file_path=str(filename))
    except Exception as e:
        return error_response(f"Error saving code: {str(e)}")


def reset_global_state():
    """Reset all global state to avoid accumulation across runs."""
    global _todos, _task_basename
    _todos = []
    _task_basename = None


# Tool definitions with explicit JSON schemas

PYTHON_EXEC_TOOL = Tool(
    name="python_exec",
    description=(
        "Execute Python code in a persistent IPython kernel.\n\n"
        "IMPORTANT: The kernel maintains state between executions!\n"
        "- Variables, functions, and imports persist across calls\n"
        "- Use print() to see output, or the last expression will be returned\n"
        "- The kernel runs in the working directory context\n\n"
        "Example:\n"
        "    First call:  x = 5\n"
        '    Second call: print(x)  # Returns: {"success": true, "stdout": "5"}\n\n'
        "    First call:  def add(a, b): return a + b\n"
        '    Second call: add(3, 4)  # Returns: {"success": true, "result": "7"}\n\n'
        "The code executes in the working directory context, so you can read/write files\n"
        "using relative paths.\n\n"
        "Args:\n"
        "    code: Python code to execute. Multi-line code is supported.\n\n"
        "Returns:\n"
        "    JSON string with execution results:\n"
        "    - success: boolean indicating if execution succeeded\n"
        "    - stdout: captured print output (if any)\n"
        "    - result: the last expression's value (if any)\n"
        "    - stderr: warnings (if any)\n"
        "    - error: error message (if execution failed)"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "title": "Code",
            },
        },
        "required": ["code"],
        "title": "python_exec",
    },
    function=python_exec,
)

SAVE_CODE_TOOL = Tool(
    name="save_code",
    description=(
        "Save the final code (fileless mode).\n\n"
        "This saves your code to {basename}_code.py where basename\n"
        "is determined from the task file name, or solution.py for inline tasks.\n\n"
        "IMPORTANT: Only call this AFTER you have:\n"
        "1. Executed the code with python_exec and confirmed it produces correct output\n"
        "2. Verified the output format matches the specification exactly (JSON keys, array shapes, value ranges)\n"
        "3. For constraint/logic problems: run an independent verification checking every constraint\n"
        "Do NOT save unverified code. If verification fails, fix the code and re-verify first.\n\n"
        "Args:\n"
        "    code: The complete Python code\n\n"
        "Returns:\n"
        "    JSON with success status and file path"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "title": "Code",
            },
        },
        "required": ["code"],
        "title": "save_code",
    },
    function=save_code,
)

TODO_WRITE_TOOL = Tool(
    name="todo_write",
    description=(
        "Replace the entire task list with validation.\n\n"
        "Each task should have:\n"
        "- id: unique identifier\n"
        "- content: task description\n"
        "- status: 'pending', 'in_progress', or 'completed'\n"
        "- priority: 'high', 'medium', or 'low'\n\n"
        "Args:\n"
        "    todos: New list of todo items\n\n"
        "Returns:\n"
        "    JSON with success status and count"
    ),
    parameters={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "title": "Todos",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        },
        "required": ["todos"],
        "title": "todo_write",
    },
    function=todo_write,
)


def create_tool_registry(todo: bool = False) -> ToolRegistry:
    """Create a tool registry with the standard coding tools.

    Args:
        todo: If True, include the todo_write tool.

    Returns:
        ToolRegistry with registered tools.
    """
    registry = ToolRegistry()
    registry.register(PYTHON_EXEC_TOOL)
    registry.register(SAVE_CODE_TOOL)
    if todo:
        registry.register(TODO_WRITE_TOOL)
    return registry
