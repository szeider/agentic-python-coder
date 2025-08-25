"""ReAct agent for Python coding tasks."""

from typing import Dict, Any, List, Optional
from pathlib import Path
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

from coder.llm import get_openrouter_llm
from coder.tools import (
    todo_write,
    python_exec,
    save_code,
    report_issue,
    working_dir,
    set_task_basename,
)

# Maximum number of steps the agent can take before stopping
# Increased from 50 to 100 to handle complex CP-bench problems that require
# extensive debugging and exploration
STEP_LIMIT = 100


def load_prompt(prompt_path: Path) -> str:
    """Load a prompt from file.

    Args:
        prompt_path: Path to the prompt file

    Returns:
        Prompt content

    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text()


def create_coding_agent(
    working_directory: str,
    system_prompt_path: Optional[str] = None,
    model: str = None,
    project_prompt: Optional[str] = None,
    with_packages: Optional[List[str]] = None,
    task_content: Optional[str] = None,
    task_basename: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """Create a ReAct agent for Python coding tasks.

    Args:
        working_directory: Directory for file operations
        system_prompt_path: Path to system prompt file
        model: Optional model name (defaults to claude-sonnet-4)
        project_prompt: Optional project-specific prompt
        with_packages: Optional list of packages for dynamic mode
        task_content: Task description/content
        task_basename: Base name for output files
        api_key: Optional API key override

    Returns:
        Configured LangGraph agent
    """
    # Set working directory for all file tools
    working_dir.set(working_directory)

    # Set task basename for fileless mode file naming
    if task_basename:
        set_task_basename(task_basename)

    # Store packages for kernel initialization
    if with_packages is not None:
        # This will be used by python_exec tool
        import os

        os.environ["CODER_WITH_PACKAGES"] = ",".join(with_packages)

    # Get LLM instance
    llm = (
        get_openrouter_llm(model=model, api_key=api_key)
        if model
        else get_openrouter_llm(api_key=api_key)
    )

    # Minimal tool set (fileless mode only now)
    tools = [python_exec, save_code, report_issue, todo_write]

    # Load prompts
    prompts = []

    # System prompt (general agent behavior)
    if system_prompt_path:
        system_prompt = load_prompt(Path(system_prompt_path))
        prompts.append(system_prompt)
    else:
        # Default minimal system prompt
        prompts.append(
            "You are a Python coding assistant with file and execution tools."
        )

    # Project prompt (from --project file)
    if project_prompt:
        prompts.append(project_prompt)

    # Task prompt handling
    if task_content:
        # Include task content directly in prompt
        prompts.append(f"<task>\n{task_content}\n</task>")

    # Combine all prompts
    combined_prompt = "\n\n".join(prompts)

    # Create the agent with memory
    checkpointer = InMemorySaver()
    agent = create_react_agent(
        llm, tools, prompt=combined_prompt, checkpointer=checkpointer
    )

    return agent


def run_agent(
    agent, user_input: str, thread_id: str = "default"
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the agent with user input, streaming progress.

    Args:
        agent: The LangGraph agent
        user_input: User's request
        thread_id: Thread ID for conversation memory

    Returns:
        Tuple of (List of messages from the agent, Statistics dictionary)
    """
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": STEP_LIMIT}

    messages = []
    current_tools = {}  # Track tool calls by ID for matching with results

    # Initialize statistics tracking
    stats = {
        "tool_usage": {},
        "token_consumption": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "execution_time_seconds": 0,
    }

    import time

    start_time = time.time()

    # Stream the agent's work
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": user_input}]},
        config=config,
        stream_mode="updates",
    ):
        # Show progress for each step
        if chunk:
            node_name = next(iter(chunk.keys()))
            node_output = chunk[node_name]

            # Extract messages from the node output
            if "messages" in node_output:
                for msg in node_output["messages"]:
                    messages.append(msg)

                    # Show tool calls
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            tool_name = tool_call.get("name") or tool_call.get(
                                "function", {}
                            ).get("name")
                            tool_id = tool_call.get("id")
                            if tool_id:
                                current_tools[tool_id] = tool_name

                            # Track tool usage statistics
                            if tool_name:
                                stats["tool_usage"][tool_name] = (
                                    stats["tool_usage"].get(tool_name, 0) + 1
                                )

                            # Show tool name with meaningful preview
                            args = tool_call.get("args", {})
                            if isinstance(args, dict):
                                if tool_name == "python_exec" and "code" in args:
                                    # For python_exec, show a meaningful description
                                    code = args["code"]
                                    # Try to extract meaningful info
                                    if "def " in code:
                                        # Function definition
                                        func_match = (
                                            code.split("def ")[1].split("(")[0]
                                            if "def " in code
                                            else ""
                                        )
                                        print(
                                            f"  {tool_name}: defining function {func_match}()"
                                        )
                                    elif "class " in code:
                                        # Class definition
                                        class_match = (
                                            code.split("class ")[1]
                                            .split("(")[0]
                                            .split(":")[0]
                                            if "class " in code
                                            else ""
                                        )
                                        print(
                                            f"  {tool_name}: defining class {class_match}"
                                        )
                                    elif ".py" in code and "open" in code:
                                        # Running a file
                                        import re

                                        file_match = re.search(
                                            r'["\']([^"\'\\/]+\.py)["\']', code
                                        )
                                        if file_match:
                                            print(
                                                f"  {tool_name}: executing file {file_match.group(1)}"
                                            )
                                        else:
                                            print(
                                                f"  {tool_name}: executing Python file"
                                            )
                                    elif (
                                        "import " in code
                                        and len(code.strip().split("\n")) == 1
                                    ):
                                        # Import statement
                                        print(f"  {tool_name}: {code.strip()}")
                                    elif (
                                        "=" in code
                                        and len(code.strip().split("\n")) == 1
                                    ):
                                        # Variable assignment
                                        var_name = code.split("=")[0].strip()
                                        print(
                                            f"  {tool_name}: assigning variable {var_name}"
                                        )
                                    elif code.strip().startswith("print("):
                                        # Print statement - show what's being printed if simple
                                        print(
                                            f"  {tool_name}: {code.strip()[:50]}{'...' if len(code.strip()) > 50 else ''}"
                                        )
                                    elif (
                                        "read_csv" in code
                                        or "read_excel" in code
                                        or "read_json" in code
                                    ):
                                        # Data loading
                                        print(f"  {tool_name}: loading data file")
                                    elif (
                                        "to_csv" in code
                                        or "to_excel" in code
                                        or "to_json" in code
                                    ):
                                        # Data saving
                                        print(f"  {tool_name}: saving data to file")
                                    elif "plt." in code or "plot" in code:
                                        # Plotting
                                        print(f"  {tool_name}: creating visualization")
                                    elif "groupby" in code or "aggregate" in code:
                                        # Data analysis
                                        print(
                                            f"  {tool_name}: analyzing/aggregating data"
                                        )
                                    else:
                                        # Generic code - show first meaningful line
                                        lines = [
                                            line.strip()
                                            for line in code.split("\n")
                                            if line.strip()
                                            and not line.strip().startswith("#")
                                        ]
                                        if lines:
                                            first_line = lines[0][:50]
                                            if len(lines[0]) > 50:
                                                first_line += "..."
                                            print(f"  {tool_name}: {first_line}")
                                        else:
                                            print(f"  {tool_name}: executing code")
                                elif tool_name == "write_file" and "file_path" in args:
                                    print(f"  {tool_name}: {args['file_path']}")
                                elif tool_name == "read_file" and "file_path" in args:
                                    print(f"  {tool_name}: {args['file_path']}")
                                elif tool_name == "todo_write" and "todos" in args:
                                    # Show todo list in nice format
                                    print(f"\n  {tool_name}:")
                                    todos = args["todos"]
                                    for todo in todos:
                                        status_symbol = (
                                            "☒"
                                            if todo["status"] == "completed"
                                            else "☐"
                                            if todo["status"] == "pending"
                                            else "▶"
                                        )
                                        print(f"     {status_symbol} {todo['content']}")
                                elif tool_name == "list_files" and "pattern" in args:
                                    print(f"  {tool_name}: {args['pattern']}")
                                else:
                                    # For other tools, show key args
                                    arg_str = str(args)[:30]
                                    if len(str(args)) > 30:
                                        arg_str += "..."
                                    print(f"  {tool_name}: {arg_str}")
                            else:
                                print(f"  {tool_name}")
                    # Extract token usage from response metadata or usage_metadata
                    if hasattr(msg, "response_metadata"):
                        usage = msg.response_metadata.get("usage", {})
                        if usage:
                            stats["token_consumption"]["input_tokens"] += usage.get(
                                "prompt_tokens", 0
                            )
                            stats["token_consumption"]["output_tokens"] += usage.get(
                                "completion_tokens", 0
                            )
                            stats["token_consumption"]["total_tokens"] += usage.get(
                                "total_tokens", 0
                            )

                    # Also check usage_metadata field (LangChain sometimes uses this)
                    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        stats["token_consumption"]["input_tokens"] += (
                            msg.usage_metadata.get("input_tokens", 0)
                        )
                        stats["token_consumption"]["output_tokens"] += (
                            msg.usage_metadata.get("output_tokens", 0)
                        )
                        stats["token_consumption"]["total_tokens"] += (
                            msg.usage_metadata.get("total_tokens", 0)
                        )

                    elif hasattr(msg, "additional_kwargs"):
                        tool_calls = msg.additional_kwargs.get("tool_calls", [])
                        for tool_call in tool_calls:
                            function = tool_call.get("function", {})
                            tool_name = function.get("name")
                            tool_id = tool_call.get("id")
                            if tool_id and tool_name:
                                current_tools[tool_id] = tool_name

                            # Track tool usage statistics
                            if tool_name:
                                stats["tool_usage"][tool_name] = (
                                    stats["tool_usage"].get(tool_name, 0) + 1
                                )

                            if tool_name:
                                # Parse arguments
                                args_str = function.get("arguments", "{}")
                                try:
                                    import json

                                    args = json.loads(args_str)
                                    if tool_name == "python_exec" and "code" in args:
                                        # For python_exec, show a meaningful description
                                        code = args["code"]
                                        if "def " in code:
                                            func_match = (
                                                code.split("def ")[1].split("(")[0]
                                                if "def " in code
                                                else ""
                                            )
                                            print(
                                                f"  {tool_name}: defining function {func_match}()"
                                            )
                                        elif "class " in code:
                                            class_match = (
                                                code.split("class ")[1]
                                                .split("(")[0]
                                                .split(":")[0]
                                                if "class " in code
                                                else ""
                                            )
                                            print(
                                                f"  {tool_name}: defining class {class_match}"
                                            )
                                        elif ".py" in code and "open" in code:
                                            import re

                                            file_match = re.search(
                                                r'["\']([^"\'\\/]+\.py)["\']', code
                                            )
                                            if file_match:
                                                print(
                                                    f"  {tool_name}: executing file {file_match.group(1)}"
                                                )
                                            else:
                                                print(
                                                    f"  {tool_name}: executing Python file"
                                                )
                                        elif (
                                            "import " in code
                                            and len(code.strip().split("\n")) == 1
                                        ):
                                            print(f"  {tool_name}: {code.strip()}")
                                        elif (
                                            "=" in code
                                            and len(code.strip().split("\n")) == 1
                                        ):
                                            var_name = code.split("=")[0].strip()
                                            print(
                                                f"  {tool_name}: assigning variable {var_name}"
                                            )
                                        elif code.strip().startswith("print("):
                                            print(
                                                f"  {tool_name}: {code.strip()[:50]}{'...' if len(code.strip()) > 50 else ''}"
                                            )
                                        elif (
                                            "read_csv" in code
                                            or "read_excel" in code
                                            or "read_json" in code
                                        ):
                                            print(f"  {tool_name}: loading data file")
                                        elif (
                                            "to_csv" in code
                                            or "to_excel" in code
                                            or "to_json" in code
                                        ):
                                            print(f"  {tool_name}: saving data to file")
                                        elif "plt." in code or "plot" in code:
                                            print(
                                                f"  {tool_name}: creating visualization"
                                            )
                                        elif "groupby" in code or "aggregate" in code:
                                            print(
                                                f"  {tool_name}: analyzing/aggregating data"
                                            )
                                        else:
                                            lines = [
                                                line.strip()
                                                for line in code.split("\n")
                                                if line.strip()
                                                and not line.strip().startswith("#")
                                            ]
                                            if lines:
                                                first_line = lines[0][:50]
                                                if len(lines[0]) > 50:
                                                    first_line += "..."
                                                print(f"  {tool_name}: {first_line}")
                                            else:
                                                print(f"  {tool_name}: executing code")
                                    elif (
                                        tool_name == "write_file"
                                        and "file_path" in args
                                    ):
                                        print(f"  {tool_name}: {args['file_path']}")
                                    elif (
                                        tool_name == "read_file" and "file_path" in args
                                    ):
                                        print(f"  {tool_name}: {args['file_path']}")
                                    elif tool_name == "todo_write" and "todos" in args:
                                        # Show todo list in nice format
                                        print(f"\n  {tool_name}:")
                                        todos = args["todos"]
                                        for todo in todos:
                                            status_symbol = (
                                                "☒"
                                                if todo["status"] == "completed"
                                                else "☐"
                                                if todo["status"] == "pending"
                                                else "▶"
                                            )
                                            print(
                                                f"     {status_symbol} {todo['content']}"
                                            )
                                    elif (
                                        tool_name == "list_files" and "pattern" in args
                                    ):
                                        print(f"  {tool_name}: {args['pattern']}")
                                    else:
                                        arg_str = str(args)[:30]
                                        if len(str(args)) > 30:
                                            arg_str += "..."
                                        print(f"  {tool_name}: {arg_str}")
                                except Exception:
                                    print(f"  {tool_name}")

                    # Show tool results
                    if hasattr(msg, "type") and msg.type == "tool":
                        tool_id = getattr(msg, "tool_call_id", None)
                        tool_name = current_tools.get(
                            tool_id, getattr(msg, "name", "unknown")
                        )

                        # Don't print checkmarks, just continue
                        pass
                    elif isinstance(msg, dict) and msg.get("type") == "tool":
                        tool_id = msg.get("tool_call_id")
                        tool_name = current_tools.get(
                            tool_id, msg.get("name", "unknown")
                        )

                        # Don't print checkmarks, just continue
                        pass

    # Calculate execution time
    stats["execution_time_seconds"] = time.time() - start_time

    return messages, stats
