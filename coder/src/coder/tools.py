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


# File operation tools
@tool
def read_file(file_path: str) -> str:
    """Read a file from the working directory.

    Args:
        file_path: Path to the file relative to working directory

    Returns:
        JSON with file content or error message
    """
    try:
        full_path = working_dir.resolve_path(file_path)
        content = full_path.read_text()
        return success_response(content, file_path=file_path)
    except FileNotFoundError:
        return error_response(f"File not found: {file_path}")
    except Exception as e:
        return error_response(f"Error reading file: {str(e)}")


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file in the working directory.

    Args:
        file_path: Path to the file relative to working directory
        content: Content to write to the file

    Returns:
        JSON with success status or error message
    """
    try:
        full_path = working_dir.resolve_path(file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return success_response(
            f"Successfully wrote to {file_path}",
            file_path=file_path,
            bytes_written=len(content),
        )
    except Exception as e:
        return error_response(f"Error writing file: {str(e)}")


@tool
def list_files(pattern: str = "*") -> str:
    """List files in the working directory.

    Args:
        pattern: Glob pattern to filter files (required, defaults to "*" for all files)

    Returns:
        JSON with list of file paths or error message
    """
    try:
        wd = working_dir.get()
        files = []

        # Simplified pattern handling
        if "**" in pattern:
            # Recursive pattern - use rglob
            matches = wd.rglob(pattern)
        else:
            # Non-recursive pattern - use glob
            matches = wd.glob(pattern)

        for path in matches:
            if path.is_file():
                try:
                    relative_path = path.relative_to(wd)
                    files.append(str(relative_path))
                except ValueError:
                    continue

        return success_response(sorted(files), pattern=pattern, count=len(files))
    except Exception as e:
        return error_response(f"Error listing files: {str(e)}")


@tool
def delete_file(file_path: str) -> str:
    """Delete a file from the working directory.

    Args:
        file_path: Path to the file relative to working directory

    Returns:
        JSON with success status or error message
    """
    try:
        full_path = working_dir.resolve_path(file_path)
        if not full_path.exists():
            return error_response(f"File not found: {file_path}")
        if not full_path.is_file():
            return error_response(f"Not a file: {file_path}")
        full_path.unlink()
        return success_response(
            f"Successfully deleted {file_path}", file_path=file_path
        )
    except Exception as e:
        return error_response(f"Error deleting file: {str(e)}")


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
_solution_code = None
_task_basename = None


def set_task_basename(basename: str):
    """Set the basename for file naming in fileless mode."""
    global _task_basename
    _task_basename = basename


@tool
def save_code(code: str) -> str:
    """Save the final code (fileless mode).

    This saves your code to {basename}_code.py where basename
    is determined from the task file name, or code.py for inline tasks.

    Args:
        code: The complete Python code

    Returns:
        JSON with success status and file path
    """
    try:
        global _solution_code, _task_basename
        _solution_code = code

        # Determine output filename
        if _task_basename:
            filename = f"{_task_basename}_code.py"
        else:
            filename = "code.py"

        # Save to working directory
        output_path = working_dir.get() / filename
        output_path.write_text(code)

        return success_response(f"Code saved to {filename}", file_path=str(filename))
    except Exception as e:
        return error_response(f"Error saving code: {str(e)}")


_reported_issues = []


@tool
def report_issue(text: str) -> str:
    """Report an environment or specification issue (fileless mode).

    Use this ONLY for:
    - Missing packages or import errors
    - Unclear task specifications
    - Environment setup problems

    Do NOT use for:
    - Logic errors in your code
    - Failed test cases
    - Debugging information

    Args:
        text: Description of the issue

    Returns:
        JSON with success status
    """
    try:
        global _reported_issues

        # Store the issue in memory to be included when log is saved
        _reported_issues.append({"type": "agent_feedback", "content": text})

        return success_response(
            "Issue reported and will be included in the log", reported=True
        )
    except Exception as e:
        return error_response(f"Error reporting issue: {str(e)}")


def get_reported_issues():
    """Get all reported issues for inclusion in the log."""
    global _reported_issues
    return _reported_issues
