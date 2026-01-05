"""ReAct agent for Python coding tasks."""

import json
import os
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from agentic_python_coder.llm import get_openrouter_llm
from agentic_python_coder.tools import (
    todo_write,
    python_exec,
    save_code,
    working_dir,
    set_task_basename,
    reset_global_state,
)

# Default maximum number of steps the agent can take before stopping
DEFAULT_STEP_LIMIT = 200


def load_prompt(prompt_path: Path) -> str:
    """Load a prompt from file."""
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text()


def create_coding_agent(
    working_directory: str,
    system_prompt: Optional[str] = None,
    system_prompt_path: Optional[str] = None,
    model: str = None,
    project_prompt: Optional[str] = None,
    with_packages: Optional[List[str]] = None,
    task_content: Optional[str] = None,
    task_basename: Optional[str] = None,
    api_key: Optional[str] = None,
    todo: bool = False,
    verbose: bool = False,
):
    """Create a ReAct agent for Python coding tasks.

    Args:
        working_directory: Directory for file operations
        system_prompt: System prompt as string (takes precedence over path)
        system_prompt_path: Path to system prompt file (used if system_prompt not provided)
        model: Optional model name (uses configured default if not specified)
        project_prompt: Optional project-specific prompt
        with_packages: Optional list of packages for dynamic mode
        task_content: Task description/content
        task_basename: Base name for output files
        api_key: Optional API key override
        todo: If True, includes todo_write tool for task tracking
        verbose: If True, print progress info (default False for library use)

    Returns:
        Configured LangGraph agent with metadata
    """
    # Reset global state to avoid accumulation across runs
    reset_global_state()

    # Set task basename for fileless mode file naming
    if task_basename:
        set_task_basename(task_basename)

    # Store packages for kernel initialization
    if with_packages is not None:
        os.environ["CODER_WITH_PACKAGES"] = ",".join(with_packages)

    # Get LLM instance
    llm = get_openrouter_llm(
        model=model or "default",
        api_key=api_key,
        verbose=verbose,
    )

    # Minimal tool set
    if todo:
        tools = [python_exec, save_code, todo_write]
    else:
        tools = [python_exec, save_code]

    # Build combined prompt
    prompts = []

    # System prompt: string takes precedence over path
    if system_prompt:
        prompts.append(system_prompt)
    elif system_prompt_path:
        prompts.append(load_prompt(Path(system_prompt_path)))
    else:
        prompts.append(
            "You are a Python coding assistant with file and execution tools."
        )

    # Project prompt
    if project_prompt:
        prompts.append(project_prompt)

    # Task content
    if task_content:
        prompts.append(f"<task>\n{task_content}\n</task>")

    combined_prompt = "\n\n".join(prompts)

    # Create the agent with memory
    checkpointer = InMemorySaver()
    agent = create_agent(
        llm, tools, system_prompt=combined_prompt, checkpointer=checkpointer
    )

    # Store metadata for run_agent to use
    agent._coder_metadata = {
        "working_directory": working_directory,
    }

    return agent


def _print_tool_progress(tool_name: str, args: dict):
    """Print progress info for a tool call."""
    if tool_name == "python_exec" and "code" in args:
        code = args["code"]
        code_stripped = code.strip()
        if "def " in code:
            func_match = code.split("def ")[1].split("(")[0]
            print(f"  {tool_name}: defining function {func_match}()")
        elif "class " in code:
            class_match = code.split("class ")[1].split("(")[0].split(":")[0]
            print(f"  {tool_name}: defining class {class_match}")
        elif "import " in code and len(code_stripped.split("\n")) == 1:
            print(f"  {tool_name}: {code_stripped}")
        elif "=" in code and len(code_stripped.split("\n")) == 1:
            var_name = code.split("=")[0].strip()
            print(f"  {tool_name}: assigning variable {var_name}")
        elif code_stripped.startswith("print("):
            print(
                f"  {tool_name}: {code_stripped[:50]}{'...' if len(code_stripped) > 50 else ''}"
            )
        elif "read_csv" in code or "read_excel" in code or "read_json" in code:
            print(f"  {tool_name}: loading data file")
        elif "to_csv" in code or "to_excel" in code or "to_json" in code:
            print(f"  {tool_name}: saving data to file")
        elif "plt." in code or "plot" in code:
            print(f"  {tool_name}: creating visualization")
        elif "groupby" in code or "aggregate" in code:
            print(f"  {tool_name}: analyzing/aggregating data")
        else:
            lines = [
                line.strip()
                for line in code.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]
            if lines:
                first_line = lines[0][:50]
                if len(lines[0]) > 50:
                    first_line += "..."
                print(f"  {tool_name}: {first_line}")
            else:
                print(f"  {tool_name}: executing code")
    elif tool_name == "todo_write" and "todos" in args:
        print(f"\n  {tool_name}:")
        todos = args["todos"]
        for todo in todos:
            status = todo.get("status", "")
            content = todo.get("content", "")
            status_symbol = "☒" if status == "completed" else "☐" if status == "pending" else "▶"
            print(f"     {status_symbol} {content}")
    else:
        args_str = str(args)
        arg_display = args_str[:30] + "..." if len(args_str) > 30 else args_str
        print(f"  {tool_name}: {arg_display}")


def _process_tool_calls(msg, stats: dict, quiet: bool):
    """Process tool calls from a message, updating stats and optionally printing."""
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tool_call in msg.tool_calls:
            tool_name = tool_call.get("name") or tool_call.get("function", {}).get(
                "name"
            )
            if tool_name:
                stats["tool_usage"][tool_name] = (
                    stats["tool_usage"].get(tool_name, 0) + 1
                )

            if not quiet and tool_name:
                args = tool_call.get("args", {})
                if isinstance(args, dict):
                    _print_tool_progress(tool_name, args)
                else:
                    print(f"  {tool_name}")

    elif hasattr(msg, "additional_kwargs"):
        tool_calls = msg.additional_kwargs.get("tool_calls", [])
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            tool_name = function.get("name")

            if tool_name:
                stats["tool_usage"][tool_name] = (
                    stats["tool_usage"].get(tool_name, 0) + 1
                )

            if not quiet and tool_name:
                args_str = function.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                    _print_tool_progress(tool_name, args)
                except json.JSONDecodeError:
                    print(f"  {tool_name}")


def _update_token_stats(msg, stats: dict):
    """Extract and update token usage statistics from a message."""
    if hasattr(msg, "response_metadata"):
        usage = msg.response_metadata.get("usage", {})
        if usage:
            stats["token_consumption"]["input_tokens"] += usage.get("prompt_tokens", 0)
            stats["token_consumption"]["output_tokens"] += usage.get(
                "completion_tokens", 0
            )
            stats["token_consumption"]["total_tokens"] += usage.get("total_tokens", 0)
            return  # Avoid double-counting if both metadata sources exist

    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
        stats["token_consumption"]["input_tokens"] += msg.usage_metadata.get(
            "input_tokens", 0
        )
        stats["token_consumption"]["output_tokens"] += msg.usage_metadata.get(
            "output_tokens", 0
        )
        stats["token_consumption"]["total_tokens"] += msg.usage_metadata.get(
            "total_tokens", 0
        )


def run_agent(
    agent,
    user_input: str,
    thread_id: str = "default",
    quiet: bool = False,
    step_limit: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the agent with user input.

    Args:
        agent: The LangGraph agent (from create_coding_agent)
        user_input: User's request
        thread_id: Thread ID for conversation memory
        quiet: If True, suppress all console output (default False)
        step_limit: Maximum agent steps before stopping (default: 200)

    Returns:
        Tuple of (List of messages from the agent, Statistics dictionary)
    """
    # Set working directory at execution time (not creation time)
    # This prevents race conditions when multiple agents are created
    metadata = getattr(agent, "_coder_metadata", {})
    if "working_directory" in metadata:
        working_dir.set(metadata["working_directory"])

    limit = step_limit if step_limit is not None else DEFAULT_STEP_LIMIT
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": limit}

    messages = []

    # Initialize statistics
    stats = {
        "tool_usage": {},
        "token_consumption": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "execution_time_seconds": 0,
    }

    start_time = time.time()

    # Stream the agent's work
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": user_input}]},
        config=config,
        stream_mode="updates",
    ):
        if chunk:
            node_name = next(iter(chunk.keys()))
            node_output = chunk[node_name]

            if "messages" in node_output:
                for msg in node_output["messages"]:
                    messages.append(msg)

                    # Process tool calls (always update stats, optionally print)
                    _process_tool_calls(msg, stats, quiet)

                    # Update token statistics
                    _update_token_stats(msg, stats)

    stats["execution_time_seconds"] = time.time() - start_time

    return messages, stats


def get_final_response(messages: List[Any]) -> Optional[str]:
    """Extract the final assistant response from agent messages.

    Args:
        messages: List of messages from run_agent

    Returns:
        The content of the last AI message, or None if not found
    """
    for msg in reversed(messages):
        # Skip tool call messages
        has_tool_calls = False
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            has_tool_calls = True
        elif hasattr(msg, "additional_kwargs") and msg.additional_kwargs.get(
            "tool_calls"
        ):
            has_tool_calls = True
        elif isinstance(msg, dict):
            if msg.get("tool_calls") or msg.get("additional_kwargs", {}).get(
                "tool_calls"
            ):
                has_tool_calls = True

        if not has_tool_calls:
            content = None
            if hasattr(msg, "content") and msg.content:
                if hasattr(msg, "type") and msg.type == "ai":
                    content = msg.content
                elif hasattr(msg, "role") and msg.role == "assistant":
                    content = msg.content
            elif isinstance(msg, dict):
                if msg.get("content") and (
                    msg.get("type") == "ai" or msg.get("role") == "assistant"
                ):
                    content = msg.get("content")

            if content:
                return content

    return None
