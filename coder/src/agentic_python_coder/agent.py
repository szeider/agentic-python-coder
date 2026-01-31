"""ReAct agent for Python coding tasks."""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path

from agentic_python_coder.llm import get_openrouter_llm, LLMConfig, DEFAULT_MODEL
from agentic_python_coder.tools import (
    ToolRegistry,
    create_tool_registry,
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


@dataclass
class CodingAgent:
    """A ReAct coding agent using direct OpenAI API calls."""

    llm_config: LLMConfig
    tools: ToolRegistry
    system_prompt: str
    working_directory: str
    messages: list = field(default_factory=list)  # persistent for interactive mode


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
) -> CodingAgent:
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
        Configured CodingAgent
    """
    # Reset global state to avoid accumulation across runs
    reset_global_state()

    # Set task basename for fileless mode file naming
    if task_basename:
        set_task_basename(task_basename)

    # Store packages for kernel initialization (clear if None to avoid state leaks)
    if with_packages is not None:
        os.environ["CODER_WITH_PACKAGES"] = ",".join(with_packages)
    else:
        os.environ.pop("CODER_WITH_PACKAGES", None)

    # Get LLM config
    llm_config = get_openrouter_llm(
        model=model or DEFAULT_MODEL,
        api_key=api_key,
        verbose=verbose,
    )

    # Create tool registry
    tools = create_tool_registry(todo=todo)

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

    return CodingAgent(
        llm_config=llm_config,
        tools=tools,
        system_prompt=combined_prompt,
        working_directory=working_directory,
    )


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
            status_symbol = (
                "☒" if status == "completed" else "☐" if status == "pending" else "▶"
            )
            print(f"     {status_symbol} {content}")
    else:
        args_str = str(args)
        arg_display = args_str[:30] + "..." if len(args_str) > 30 else args_str
        print(f"  {tool_name}: {arg_display}")


def run_agent(
    agent: CodingAgent,
    user_input: str,
    thread_id: str = "default",
    quiet: bool = False,
    step_limit: Optional[int] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the agent with user input using a manual ReAct loop.

    Args:
        agent: The CodingAgent (from create_coding_agent)
        user_input: User's request
        thread_id: Thread ID (kept for backward compat, ignored)
        quiet: If True, suppress all console output (default False)
        step_limit: Maximum agent steps before stopping (default: 200)

    Returns:
        Tuple of (List of new messages from this call, Statistics dictionary)
    """
    # Set working directory at execution time (not creation time)
    # This prevents race conditions when multiple agents are created
    working_dir.set(agent.working_directory)

    limit = step_limit if step_limit is not None else DEFAULT_STEP_LIMIT

    # Initialize statistics
    stats = {
        "tool_usage": {},
        "token_consumption": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "execution_time_seconds": 0,
    }

    start_time = time.time()

    # Seed messages if empty (first call)
    if not agent.messages:
        agent.messages.append({"role": "system", "content": agent.system_prompt})

    # Track where new messages start
    new_messages_start = len(agent.messages)

    # Append user message
    agent.messages.append({"role": "user", "content": user_input})

    # Get OpenAI tools
    openai_tools = agent.tools.get_openai_tools()

    # ReAct loop
    for step_num in range(limit):
        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "model": agent.llm_config.model,
            "messages": agent.messages,
            **agent.llm_config.api_params,
        }

        if openai_tools:
            request_kwargs["tools"] = openai_tools
            request_kwargs["tool_choice"] = "auto"

        # Call API
        response = agent.llm_config.client.chat.completions.create(**request_kwargs)

        # Track tokens
        if response.usage:
            stats["token_consumption"]["input_tokens"] += response.usage.prompt_tokens
            stats["token_consumption"]["output_tokens"] += (
                response.usage.completion_tokens
            )
            stats["token_consumption"]["total_tokens"] += response.usage.total_tokens

        if not response.choices:
            break

        assistant_message = response.choices[0].message

        # Check for tool calls
        if assistant_message.tool_calls:
            # Append the assistant message (with tool_calls) to history
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_message.tool_calls
                    ],
                }
            )

            # Execute each tool call
            for tc in assistant_message.tool_calls:
                tool_name = tc.function.name
                tool_args_str = tc.function.arguments

                # Track tool usage
                stats["tool_usage"][tool_name] = (
                    stats["tool_usage"].get(tool_name, 0) + 1
                )

                # Parse arguments
                try:
                    tool_args = json.loads(tool_args_str)
                except (json.JSONDecodeError, TypeError):
                    # Feed error back to model
                    tool_result = json.dumps(
                        {"error": f"Invalid JSON arguments: {tool_args_str}"}
                    )
                    tool_args = {}
                else:
                    # Print progress before execution
                    if not quiet:
                        _print_tool_progress(tool_name, tool_args)

                    # Execute tool
                    tool = agent.tools.get(tool_name)
                    if tool is not None:
                        try:
                            tool_result = tool.execute(**tool_args)
                        except Exception as e:
                            tool_result = json.dumps(
                                {"error": f"Tool '{tool_name}' failed: {e}"}
                            )
                    else:
                        tool_result = json.dumps(
                            {"error": f"Unknown tool: {tool_name}"}
                        )

                # Append tool result to history
                agent.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )

        else:
            # No tool calls — final answer
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.content or "",
                }
            )
            break

    stats["execution_time_seconds"] = time.time() - start_time

    # Return only new messages from this call
    new_messages = agent.messages[new_messages_start:]
    return new_messages, stats


def get_final_response(messages: List[Any]) -> Optional[str]:
    """Extract the final assistant response from agent messages.

    Args:
        messages: List of messages from run_agent (dicts)

    Returns:
        The content of the last assistant message without tool calls, or None
    """
    for msg in reversed(messages):
        # Handle dict messages (new format)
        if isinstance(msg, dict):
            if msg.get("tool_calls"):
                continue
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        # Handle object messages (backward compat)
        elif hasattr(msg, "role") and hasattr(msg, "content"):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                continue
            if msg.role == "assistant" and msg.content:
                return msg.content

    return None
