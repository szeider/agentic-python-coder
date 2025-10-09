"""Command-line interface for the Python coding agent."""

import argparse
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Optional, List, Any, Dict

# Suppress specific warnings that are known and not problematic
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain")
warnings.filterwarnings("ignore", message=".*PythonREPL.*")

from coder.agent import create_coding_agent, run_agent  # noqa: E402
from coder.project_md import (  # noqa: E402
    parse_project_file,
    check_packages_available,
    create_project_prompt,
)
from coder.llm import MODEL_STRING, MODEL_REGISTRY  # noqa: E402


def display_statistics(stats: Dict[str, Any]):
    """Display execution statistics in a formatted way."""
    if not stats:
        return

    print("\n" + "=" * 50)
    print("📊 Execution Statistics")
    print("=" * 50)

    # Tool usage
    if stats.get("tool_usage"):
        print("\n🔧 Tool Usage:")
        for tool_name, count in sorted(stats["tool_usage"].items()):
            print(f"  {tool_name:20} {count:3} calls")
    else:
        print("\n🔧 Tool Usage: No tools were called")

    # Token consumption
    token_stats = stats.get("token_consumption", {})
    if any(token_stats.values()):
        print("\n💬 Token Consumption:")
        print(f"  Input tokens:        {token_stats.get('input_tokens', 0):,}")
        print(f"  Output tokens:       {token_stats.get('output_tokens', 0):,}")
        print(f"  Total tokens:        {token_stats.get('total_tokens', 0):,}")
    else:
        print("\n💬 Token Consumption: No token data available")

    # Execution time
    exec_time = stats.get("execution_time_seconds", 0)
    if exec_time > 0:
        minutes = int(exec_time // 60)
        seconds = exec_time % 60
        if minutes > 0:
            print(f"\n⏱️  Execution time: {minutes}m {seconds:.1f}s")
        else:
            print(f"\n⏱️  Execution time: {seconds:.1f}s")

    print("=" * 50 + "\n")


def main():
    """Main CLI entry point."""
    # Override print to flush immediately for better real-time output
    import functools
    import builtins

    if not hasattr(builtins.print, "_original"):
        builtins._original_print = builtins.print
        builtins.print = functools.partial(builtins._original_print, flush=True)

    parser = argparse.ArgumentParser(
        description="Coder - AI-powered Python coding assistant", usage="coder [task]"
    )

    parser.add_argument(
        "task_input",
        nargs="?",
        help="Task for the coder (inline task or reads from task.md if not provided)",
    )

    parser.add_argument(
        "--task",
        "-t",
        dest="task_file",
        help="Path to task file (creates {basename}_code.py and {basename}.jsonl)",
    )

    parser.add_argument("--model", help=f"Model to use (default: {MODEL_STRING})")

    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Interactive mode"
    )

    parser.add_argument(
        "--project",
        "-p",
        help="Path to project markdown file with examples and available packages",
    )

    parser.add_argument(
        "--with",
        action="append",
        dest="with_packages",
        help="Additional packages to include (can be used multiple times, e.g., --with pandas --with numpy)",
    )

    parser.add_argument(
        "--dir",
        "-d",
        dest="working_dir",
        help="Working directory for execution (default: current directory)",
    )

    parser.add_argument(
        "--api-key",
        dest="api_key",
        help="OpenRouter API key (overrides ~/.config/coder/.env)",
    )

    parser.add_argument(
        "--todo",
        action="store_true",
        help="Enable todo_write tool for task tracking and planning",
    )

    args = parser.parse_args()

    # Resolve task file path BEFORE changing directory (if using --dir)
    task_file_path = None
    task_content = None

    if args.task_file:
        # --task flag provided: resolve path before chdir
        task_file_path = Path(args.task_file).resolve()
        if not task_file_path.exists():
            print(f"Error: Task file not found: {args.task_file}")
            sys.exit(1)
        task_content = task_file_path.read_text()

    # Resolve project file path BEFORE changing directory
    if args.project:
        args.project = str(Path(args.project).resolve())

    # Set up working directory
    if args.working_dir:
        working_dir = Path(args.working_dir).resolve()
        working_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(working_dir)
    else:
        working_dir = Path.cwd()

    # Determine task handling
    if args.task_file:
        # Task already loaded above
        pass
    elif args.task_input:
        # Positional task: treat as inline task
        task_content = args.task_input

    # Validate package specifications if provided
    if args.with_packages:
        import re

        # Basic validation for package specs
        pattern = re.compile(
            r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?"  # Package name
            r"(\[[a-zA-Z0-9,_-]+\])?"  # Optional extras
            r"([@=!<>~]+[a-zA-Z0-9.*+!,\-_.]+)?$"  # Optional version spec
        )

        invalid_packages = []
        for pkg in args.with_packages:
            if not pattern.match(pkg):
                invalid_packages.append(pkg)

        if invalid_packages:
            print(
                f"❌ Error: Invalid package specifications: {', '.join(invalid_packages)}"
            )
            print(
                "Expected format: 'package' or 'package>=version' or 'package[extras]'"
            )
            print("\nExamples:")
            print("  --with pandas")
            print("  --with 'numpy>=1.20'")
            print("  --with 'requests[security]'")
            sys.exit(1)

    # Validate model if provided
    if args.model:
        # Check if the model is in the registry or is a full path
        if args.model not in MODEL_REGISTRY and "/" not in args.model:
            available_models = sorted(
                [m for m in MODEL_REGISTRY.keys() if m != "default"]
            )
            print(f"❌ Error: Unknown model: '{args.model}'")
            print("\nAvailable models:")
            for model in available_models:
                print(f"  - {model}")
            print("\nUsage:")
            print('  coder --model claude "your task"     # Claude Sonnet 4 (default)')
            print('  coder --model deepseek "your task"   # DeepSeek v3.1')
            print('  coder --model grok "your task"       # X.AI Grok')
            print('  coder --model qwen "your task"       # Qwen3 Coder')
            print('  coder --model gemini "your task"     # Google Gemini Pro 2.5')
            print('  coder --model gpt "your task"        # OpenAI GPT-5')
            sys.exit(1)

    # Validate task is provided
    if not task_content:
        print("Error: No task provided")
        print("\nUsage:")
        print('  coder "your task here"     # Inline task')
        print("  coder --task problem.md    # Task from file")
        sys.exit(1)

    # Load project if specified
    project_prompt = None
    if args.project:
        try:
            # Parse the project file
            packages, content = parse_project_file(args.project)

            unavailable = []  # Initialize to empty list
            if packages:
                print(f"📦 Project packages: {', '.join(packages)}")

                # Check if packages are available
                unavailable = check_packages_available(packages)
                if unavailable:
                    print("\n⚠️  Warning: The following packages are not installed:")
                    for pkg in unavailable:
                        print(f"   - {pkg}")
                    print("\nContinuing anyway...\n")

            # Create the project prompt
            project_prompt = create_project_prompt(packages, content, unavailable)
            print(f"✅ Loaded project from: {args.project}")

        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error loading project: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)

    # Run the agent
    try:
        run_coder(
            working_dir=working_dir,
            model=args.model,
            interactive=args.interactive,
            project_prompt=project_prompt,
            with_packages=args.with_packages,
            task_content=task_content,
            task_file_path=task_file_path,
            api_key=args.api_key,
            todo=args.todo,
        )
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def get_system_prompt_path(todo: bool = False) -> Path:
    """Get the path to the system prompt in the codebase."""
    # System prompt is in the coder package
    base_dir = Path(__file__).parent.parent.parent

    if todo:
        system_prompt_path = base_dir / "prompts" / "system_todo.md"
    else:
        system_prompt_path = base_dir / "prompts" / "system.md"

    if not system_prompt_path.exists():
        raise FileNotFoundError(f"System prompt not found at: {system_prompt_path}")

    return system_prompt_path


def save_conversation_log(
    working_dir: Path,
    messages: List[Any],
    stats: Optional[Dict[str, Any]] = None,
    task_basename: Optional[str] = None,
):
    """Save conversation history as JSON Lines format."""
    if task_basename:
        log_path = working_dir / f"{task_basename}.jsonl"
    else:
        log_path = working_dir / "log.jsonl"

    # Write as JSON Lines format
    with open(log_path, "w") as f:
        # Start event
        f.write(
            json.dumps({"event": "start", "task": task_basename or "inline"}) + "\n"
        )

        # Process messages to extract events
        for msg in messages:
            # Extract tool calls and responses
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    # Handle different tool call formats
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
                    elif tool_name == "report_issue":
                        f.write(
                            json.dumps(
                                {
                                    "event": "report_issue",
                                    "issue": tool_args.get("text", "")[
                                        :200
                                    ],  # First 200 chars
                                }
                            )
                            + "\n"
                        )
                    else:
                        f.write(
                            json.dumps({"event": "tool_call", "tool": tool_name}) + "\n"
                        )

            # Handle tool responses
            if hasattr(msg, "content") and isinstance(msg.content, str):
                try:
                    # Try to parse tool response
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

        # Add statistics if provided
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

        # Add agent feedback if any
        from coder.tools import get_reported_issues

        reported_issues = get_reported_issues()
        if reported_issues:
            for issue in reported_issues:
                f.write(
                    json.dumps(
                        {"event": "agent_feedback", "content": issue.get("content", "")}
                    )
                    + "\n"
                )

        # Complete event
        f.write(
            json.dumps(
                {
                    "event": "complete",
                    "status": "success"
                    if not reported_issues
                    else "success_with_issues",
                }
            )
            + "\n"
        )

    return log_path


def run_coder(
    working_dir: Path,
    model: Optional[str],
    interactive: bool,
    project_prompt: Optional[str] = None,
    with_packages: Optional[List[str]] = None,
    task_content: Optional[str] = None,
    task_file_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    todo: bool = False,
):
    """Run the coder agent."""
    messages = []
    try:
        # Get system prompt from codebase
        base_dir = Path(__file__).parent.parent.parent

        if todo:
            system_prompt_path = base_dir / "prompts" / "system_todo.md"
        else:
            system_prompt_path = base_dir / "prompts" / "system.md"

        if not system_prompt_path.exists():
            raise FileNotFoundError(f"System prompt not found at: {system_prompt_path}")

        # Print info
        print("🚀 Running coder")

        if with_packages:
            print(f"📦 Dynamic packages: {', '.join(with_packages)}")

        # Determine task basename for output files
        task_basename = None
        if task_file_path:
            task_basename = task_file_path.stem

        # Create agent
        print(f"🤖 Creating agent with model: {model or MODEL_STRING}")
        agent = create_coding_agent(
            working_directory=str(working_dir),
            system_prompt_path=str(system_prompt_path),
            model=model,
            project_prompt=project_prompt,
            with_packages=with_packages,
            task_content=task_content,
            task_basename=task_basename,
            api_key=api_key,
            todo=todo,
        )

        if interactive:
            run_interactive(agent, working_dir, project_prompt)
        else:
            # Single run mode
            message = "Please complete the task described in the instructions."

            messages, stats = run_agent(agent, message)

            # Save conversation log with statistics
            log_path = save_conversation_log(
                working_dir, messages, stats, task_basename
            )

            # Print the last assistant message
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

                # Find content message
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
                        # Use rich for markdown formatting
                        try:
                            from rich.console import Console
                            from rich.markdown import Markdown

                            console = Console()
                            print()  # Add newline before response
                            console.print(Markdown(content))
                        except ImportError:
                            # Fallback to plain text if rich is not available
                            print("\nAgent response:")
                            print("-" * 40)
                            print(content)
                        break

            # Display statistics
            display_statistics(stats)

            print(f"📄 Log saved to: {log_path}")

    except Exception:
        # Save partial conversation if available
        if messages:
            log_path = save_conversation_log(
                working_dir, messages, task_basename=task_basename
            )
            print(f"\n📄 Partial log saved to: {log_path}")
        raise


def run_interactive(agent, working_dir: Path, project_prompt: Optional[str] = None):
    """Run the agent in interactive mode."""
    print(f"\n🚀 Interactive mode - working in: {working_dir}")
    if project_prompt:
        print("📦 Project configuration loaded")
    print("Type 'exit' or 'quit' to stop.\n")

    thread_id = "interactive"
    all_messages = []
    cumulative_stats = {
        "tool_usage": {},
        "token_consumption": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "execution_time_seconds": 0,
    }

    try:
        while True:
            try:
                user_input = input("👤 You: ").strip()

                if user_input.lower() in ["exit", "quit"]:
                    print("👋 Goodbye!")
                    break

                if not user_input:
                    continue

                print("\n🤖 Agent working...\n")
                messages, stats = run_agent(agent, user_input, thread_id)
                all_messages.extend(messages)

                # Update cumulative statistics
                for tool, count in stats.get("tool_usage", {}).items():
                    cumulative_stats["tool_usage"][tool] = (
                        cumulative_stats["tool_usage"].get(tool, 0) + count
                    )

                token_stats = stats.get("token_consumption", {})
                cumulative_stats["token_consumption"]["input_tokens"] += (
                    token_stats.get("input_tokens", 0)
                )
                cumulative_stats["token_consumption"]["output_tokens"] += (
                    token_stats.get("output_tokens", 0)
                )
                cumulative_stats["token_consumption"]["total_tokens"] += (
                    token_stats.get("total_tokens", 0)
                )
                cumulative_stats["execution_time_seconds"] += stats.get(
                    "execution_time_seconds", 0
                )

                # Save after each interaction
                save_conversation_log(working_dir, all_messages, cumulative_stats)

                # Print the last assistant message
                for msg in reversed(messages):
                    # Skip tool call messages
                    has_tool_calls = False
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        has_tool_calls = True
                    elif hasattr(
                        msg, "additional_kwargs"
                    ) and msg.additional_kwargs.get("tool_calls"):
                        has_tool_calls = True
                    elif isinstance(msg, dict):
                        if msg.get("tool_calls") or msg.get(
                            "additional_kwargs", {}
                        ).get("tool_calls"):
                            has_tool_calls = True

                    # Find content message
                    if not has_tool_calls:
                        content = None
                        if hasattr(msg, "content") and msg.content:
                            if hasattr(msg, "type") and msg.type == "ai":
                                content = msg.content
                            elif hasattr(msg, "role") and msg.role == "assistant":
                                content = msg.content
                        elif isinstance(msg, dict):
                            if msg.get("content") and (
                                msg.get("type") == "ai"
                                or msg.get("role") == "assistant"
                            ):
                                content = msg.get("content")

                        if content:
                            # Use rich for markdown formatting
                            try:
                                from rich.console import Console
                                from rich.markdown import Markdown

                                console = Console()
                                print()  # Add newline
                                console.print("[bold]Agent:[/bold]")
                                console.print(Markdown(content))
                                print()  # Add newline after
                            except ImportError:
                                # Fallback to plain text
                                print(f"\n🤖 Agent: {content}\n")
                            break

            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}\n")
    finally:
        # Save final conversation log with statistics
        if all_messages:
            log_path = save_conversation_log(
                working_dir, all_messages, cumulative_stats
            )
            # Display final cumulative statistics
            if cumulative_stats and any(
                cumulative_stats.get("tool_usage", {}).values()
                or cumulative_stats.get("token_consumption", {}).values()
            ):
                print("\n📊 Session Summary:")
                display_statistics(cumulative_stats)
            print(f"📄 Log saved to: {log_path}")


if __name__ == "__main__":
    main()
