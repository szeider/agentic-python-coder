"""High-level runner for coding tasks."""

import json
from pathlib import Path
from typing import Optional, List, Any, Dict

from agentic_python_coder.agent import create_coding_agent, run_agent


def get_system_prompt_path(todo: bool = False) -> Path:
    """Get the path to the system prompt in the codebase.

    Handles both development (editable) and installed package structures.
    """
    current_dir = Path(__file__).parent

    # Check if prompts is at current level (installed package)
    prompts_dir = current_dir / "prompts"
    if not prompts_dir.exists():
        # Editable install: go up to coder/ root, then to prompts/
        prompts_dir = current_dir.parent.parent / "prompts"

    if todo:
        system_prompt_path = prompts_dir / "system_todo.md"
    else:
        system_prompt_path = prompts_dir / "system.md"

    if not system_prompt_path.exists():
        raise FileNotFoundError(
            f"System prompt not found at: {system_prompt_path}\n"
            f"Searched from: {Path(__file__)}"
        )

    return system_prompt_path


def save_conversation_log(
    working_dir: Path,
    messages: List[Any],
    stats: Optional[Dict[str, Any]] = None,
    task_basename: Optional[str] = None,
) -> Path:
    """Save conversation history as JSON Lines format.

    Args:
        working_dir: Directory to save log
        messages: List of agent messages (dicts from the new format)
        stats: Execution statistics
        task_basename: Base name for log file

    Returns:
        Path to saved log file
    """
    if task_basename:
        log_path = working_dir / f"{task_basename}.jsonl"
    else:
        log_path = working_dir / "log.jsonl"

    with open(log_path, "w", encoding="utf-8") as f:
        # Start event
        f.write(
            json.dumps({"event": "start", "task": task_basename or "inline"}) + "\n"
        )

        # Process messages
        for msg in messages:
            # Handle dict messages (new format)
            if isinstance(msg, dict):
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    for tool_call in tool_calls:
                        func = tool_call.get("function", {})
                        tool_name = func.get("name", "unknown")
                        try:
                            tool_args = json.loads(func.get("arguments", "{}"))
                        except (json.JSONDecodeError, TypeError):
                            tool_args = {}

                        if tool_name == "todo_write":
                            todos = tool_args.get("todos", [])
                            f.write(
                                json.dumps(
                                    {
                                        "event": "todo",
                                        "action": "update",
                                        "count": len(todos),
                                        "tasks": [
                                            {
                                                "content": t.get("content", ""),
                                                "status": t.get("status", ""),
                                            }
                                            for t in todos
                                        ],
                                    }
                                )
                                + "\n"
                            )
                        elif tool_name == "python_exec":
                            f.write(
                                json.dumps(
                                    {
                                        "event": "python_exec",
                                        "code_length": len(tool_args.get("code", "")),
                                    }
                                )
                                + "\n"
                            )
                        elif tool_name == "save_code":
                            f.write(
                                json.dumps(
                                    {
                                        "event": "save_code",
                                        "code_length": len(tool_args.get("code", "")),
                                    }
                                )
                                + "\n"
                            )
                        else:
                            f.write(
                                json.dumps({"event": "tool_call", "tool": tool_name})
                                + "\n"
                            )

                # Handle tool responses (role=tool messages with content)
                elif msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                    try:
                        content_data = json.loads(msg["content"])
                        if "success" in content_data:
                            f.write(
                                json.dumps(
                                    {
                                        "event": "tool_response",
                                        "success": content_data.get("success", False),
                                        "error": content_data.get("error")
                                        if not content_data.get("success")
                                        else None,
                                    }
                                )
                                + "\n"
                            )
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Handle object messages (backward compat)
            elif hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if isinstance(tool_call, dict):
                        tool_name = tool_call.get("name", "unknown")
                        tool_args = tool_call.get("args", {})
                    else:
                        tool_name = getattr(tool_call, "name", "unknown")
                        tool_args = getattr(tool_call, "args", {})

                    if tool_name == "todo_write":
                        todos = tool_args.get("todos", [])
                        f.write(
                            json.dumps(
                                {
                                    "event": "todo",
                                    "action": "update",
                                    "count": len(todos),
                                    "tasks": [
                                        {
                                            "content": t.get("content", ""),
                                            "status": t.get("status", ""),
                                        }
                                        for t in todos
                                    ],
                                }
                            )
                            + "\n"
                        )
                    elif tool_name == "python_exec":
                        f.write(
                            json.dumps(
                                {
                                    "event": "python_exec",
                                    "code_length": len(tool_args.get("code", "")),
                                }
                            )
                            + "\n"
                        )
                    elif tool_name == "save_code":
                        f.write(
                            json.dumps(
                                {
                                    "event": "save_code",
                                    "code_length": len(tool_args.get("code", "")),
                                }
                            )
                            + "\n"
                        )
                    else:
                        f.write(
                            json.dumps({"event": "tool_call", "tool": tool_name}) + "\n"
                        )

            elif hasattr(msg, "content") and isinstance(msg.content, str):
                try:
                    content_data = json.loads(msg.content)
                    if "success" in content_data:
                        f.write(
                            json.dumps(
                                {
                                    "event": "tool_response",
                                    "success": content_data.get("success", False),
                                    "error": content_data.get("error")
                                    if not content_data.get("success")
                                    else None,
                                }
                            )
                            + "\n"
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

        # Statistics
        if stats:
            f.write(
                json.dumps(
                    {
                        "event": "statistics",
                        "tool_usage": stats.get("tool_usage", {}),
                        "tokens": stats.get("token_consumption", {}),
                        "execution_time": stats.get("execution_time_seconds", 0),
                    }
                )
                + "\n"
            )

        # Complete event
        f.write(
            json.dumps(
                {
                    "event": "complete",
                    "status": "success",
                }
            )
            + "\n"
        )

    return log_path


def solve_task(
    task: str,
    working_directory: str = ".",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    system_prompt_path: Optional[str] = None,
    project_prompt: Optional[str] = None,
    with_packages: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    todo: bool = False,
    quiet: bool = False,
    save_log: bool = True,
    task_basename: Optional[str] = None,
    step_limit: Optional[int] = None,
) -> tuple[List[Any], Dict[str, Any], Optional[Path]]:
    """Run a complete coding task end-to-end.

    This is the main library entry point for running coding tasks.

    Args:
        task: The task description/instructions
        working_directory: Directory for file operations (default: current dir)
        model: Model name or alias (default: claude-sonnet-4.5)
        system_prompt: Custom system prompt as string (takes precedence over path)
        system_prompt_path: Path to system prompt file
        project_prompt: Project-specific context/examples
        with_packages: Additional packages to install dynamically
        api_key: OpenRouter API key (default: from env/config)
        todo: Enable todo_write tool for task tracking
        quiet: Suppress console output (default: False)
        save_log: Save conversation log to file (default: True)
        task_basename: Base name for output files
        step_limit: Maximum agent steps before stopping (default: 200)

    Returns:
        Tuple of (messages, stats, log_path)
        - messages: List of agent messages
        - stats: Execution statistics dict
        - log_path: Path to log file (or None if save_log=False)

    Example:
        >>> from agentic_python_coder import solve_task
        >>> messages, stats, _ = solve_task(
        ...     "Write a fibonacci function",
        ...     working_directory="/tmp/workspace",
        ...     quiet=True,
        ... )
    """
    working_dir = Path(working_directory).resolve()
    working_dir.mkdir(parents=True, exist_ok=True)

    # Load system prompt: string > path > default
    if system_prompt is None:
        if system_prompt_path is not None:
            system_prompt = Path(system_prompt_path).read_text()
        else:
            default_path = get_system_prompt_path(todo)
            system_prompt = default_path.read_text()

    # Create agent
    agent = create_coding_agent(
        working_directory=str(working_dir),
        system_prompt=system_prompt,
        model=model,
        project_prompt=project_prompt,
        with_packages=with_packages,
        task_content=task,
        task_basename=task_basename,
        api_key=api_key,
        todo=todo,
        verbose=not quiet,
    )

    # Run agent
    message = "Please complete the task described in the instructions."
    messages, stats = run_agent(agent, message, quiet=quiet, step_limit=step_limit)

    # Save log
    log_path = None
    if save_log:
        log_path = save_conversation_log(working_dir, messages, stats, task_basename)

    return messages, stats, log_path
