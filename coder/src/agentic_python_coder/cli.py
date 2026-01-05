"""Command-line interface for the Python coding agent."""

import argparse
import os
import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any
from importlib import resources

from agentic_python_coder.runner import (
    solve_task,
    get_system_prompt_path,
    save_conversation_log,
)
from agentic_python_coder.agent import (
    create_coding_agent,
    run_agent,
    get_final_response,
)
from agentic_python_coder.project_md import (
    parse_project_file,
    check_packages_available,
    create_project_prompt,
)
from agentic_python_coder.llm import (
    DEFAULT_MODEL,
    list_available_models,
    load_model_config,
)
from agentic_python_coder import __version__


def display_statistics(stats: Dict[str, Any]):
    """Display execution statistics in a formatted way."""
    if not stats:
        return

    print("\n" + "=" * 50)
    print("Execution Statistics")
    print("=" * 50)

    if stats.get("tool_usage"):
        print("\nTool Usage:")
        for tool_name, count in sorted(stats["tool_usage"].items()):
            print(f"  {tool_name:20} {count:3} calls")
    else:
        print("\nTool Usage: No tools were called")

    token_stats = stats.get("token_consumption", {})
    if any(token_stats.values()):
        print("\nToken Consumption:")
        print(f"  Input tokens:        {token_stats.get('input_tokens', 0):,}")
        print(f"  Output tokens:       {token_stats.get('output_tokens', 0):,}")
        print(f"  Total tokens:        {token_stats.get('total_tokens', 0):,}")
    else:
        print("\nToken Consumption: No token data available")

    exec_time = stats.get("execution_time_seconds", 0)
    if exec_time > 0:
        minutes = int(exec_time // 60)
        seconds = exec_time % 60
        if minutes > 0:
            print(f"\nExecution time: {minutes}m {seconds:.1f}s")
        else:
            print(f"\nExecution time: {seconds:.1f}s")

    print("=" * 50 + "\n")


def display_response(messages):
    """Display the final agent response with rich formatting."""
    content = get_final_response(messages)
    if content:
        try:
            from rich.console import Console
            from rich.markdown import Markdown

            console = Console()
            print()
            console.print(Markdown(content))
        except ImportError:
            print("\nAgent response:")
            print("-" * 40)
            print(content)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Coder - AI-powered Python coding assistant", usage="coder [task]"
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
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

    parser.add_argument(
        "--model", help=f"Model name or JSON file (default: {DEFAULT_MODEL})"
    )

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
        help="Additional packages to include (e.g., --with pandas --with numpy)",
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

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress console output during execution",
    )

    parser.add_argument(
        "--step-limit",
        type=int,
        dest="step_limit",
        help="Maximum agent steps before stopping (default: 200)",
    )

    parser.add_argument(
        "--init",
        nargs="?",
        const="all",
        metavar="TEMPLATE",
        help="Initialize example templates (cpmpy, clingo, regex, or all)",
    )

    return parser.parse_args()


def copy_resource_dir(source_path, dest_path: Path):
    """Recursively copy a resource directory to destination."""
    dest_path.mkdir(parents=True, exist_ok=True)

    for item in source_path.iterdir():
        dest_item = dest_path / item.name
        if item.is_file():
            # Skip __pycache__ and .pyc files
            if item.name.endswith(".pyc") or item.name == "__pycache__":
                continue
            # Read and write file content
            content = item.read_bytes()
            dest_item.write_bytes(content)
        elif item.is_dir():
            if item.name == "__pycache__":
                continue
            copy_resource_dir(item, dest_item)


def init_examples(template: str = "all"):
    """Initialize example templates in current directory."""
    available = ["cpmpy", "clingo", "regex"]

    if template != "all" and template not in available:
        print(f"Error: Unknown template '{template}'")
        print(f"Available templates: {', '.join(available)}, all")
        sys.exit(1)

    templates = available if template == "all" else [template]

    # Get examples from package
    examples_pkg = resources.files("agentic_python_coder.examples")

    output_dir = Path("coder-examples")

    for tmpl in templates:
        source = examples_pkg.joinpath(tmpl)
        dest = output_dir / tmpl

        if dest.exists():
            print(f"  {tmpl}/ already exists, skipping")
            continue

        copy_resource_dir(source, dest)
        print(f"  {tmpl}/ created")

    print(f"\nExamples initialized in: {output_dir.absolute()}")
    print("\nUsage:")
    print(
        f"  coder --with cpmpy --project {output_dir}/cpmpy/cpmpy.md --task {output_dir}/cpmpy/sample_tasks/n_queens.md"
    )


def validate_packages(packages):
    """Validate package specifications."""
    if not packages:
        return

    pattern = re.compile(
        r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?"
        r"(\[[a-zA-Z0-9,_-]+\])?"
        r"([@=!<>~]+[a-zA-Z0-9.*+!,\-_.]+)?$"
    )

    invalid = [pkg for pkg in packages if not pattern.match(pkg)]
    if invalid:
        print(f"Error: Invalid package specifications: {', '.join(invalid)}")
        print("Expected format: 'package' or 'package>=version' or 'package[extras]'")
        sys.exit(1)


def validate_model(model):
    """Validate model name or JSON file."""
    if not model:
        return
    try:
        load_model_config(model)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nAvailable built-in models:")
        for m in list_available_models():
            print(f"  - {m}")
        print("\nOr provide a path to a custom model JSON file.")
        sys.exit(1)


def load_project_prompt(project_path: str) -> Optional[str]:
    """Load and parse a project file."""
    try:
        packages, content = parse_project_file(project_path)

        unavailable = []
        if packages:
            print(f"Project packages: {', '.join(packages)}")
            unavailable = check_packages_available(packages)
            if unavailable:
                print("\nWarning: The following packages are not installed:")
                for pkg in unavailable:
                    print(f"   - {pkg}")
                print("\nContinuing anyway...\n")

        prompt = create_project_prompt(packages, content, unavailable)
        print(f"Loaded project from: {project_path}")
        return prompt

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading project: {e}")
        sys.exit(1)


def run_interactive(
    working_dir: Path, model: str, project_prompt: str, api_key: str, todo: bool
):
    """Run the agent in interactive mode."""
    print(f"\nInteractive mode - working in: {working_dir}")
    if project_prompt:
        print("Project configuration loaded")
    print("Type 'exit' or 'quit' to stop.\n")

    # Load system prompt
    system_prompt = get_system_prompt_path(todo).read_text()

    # Create agent once for the session
    agent = create_coding_agent(
        working_directory=str(working_dir),
        system_prompt=system_prompt,
        model=model,
        project_prompt=project_prompt,
        api_key=api_key,
        todo=todo,
        verbose=True,
    )

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
                user_input = input("You: ").strip()

                if user_input.lower() in ["exit", "quit"]:
                    print("Goodbye!")
                    break

                if not user_input:
                    continue

                print("\nAgent working...\n")
                messages, stats = run_agent(agent, user_input, thread_id, quiet=False)
                all_messages.extend(messages)

                # Update cumulative stats
                for tool, count in stats.get("tool_usage", {}).items():
                    cumulative_stats["tool_usage"][tool] = (
                        cumulative_stats["tool_usage"].get(tool, 0) + count
                    )

                for key in ["input_tokens", "output_tokens", "total_tokens"]:
                    cumulative_stats["token_consumption"][key] += stats.get(
                        "token_consumption", {}
                    ).get(key, 0)

                cumulative_stats["execution_time_seconds"] += stats.get(
                    "execution_time_seconds", 0
                )

                # Save after each interaction
                save_conversation_log(working_dir, all_messages, cumulative_stats)

                # Display response
                display_response(messages)
                print()

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}\n")

    finally:
        if all_messages:
            log_path = save_conversation_log(
                working_dir, all_messages, cumulative_stats
            )
            if any(cumulative_stats.get("tool_usage", {}).values()):
                print("\nSession Summary:")
                display_statistics(cumulative_stats)
            print(f"Log saved to: {log_path}")


def main():
    """Main CLI entry point."""
    # Flush output immediately
    import functools
    import builtins

    if not hasattr(builtins, "_original_print"):
        builtins._original_print = builtins.print
        builtins.print = functools.partial(builtins._original_print, flush=True)

    args = parse_args()

    # Handle --init command
    if args.init:
        print("Initializing example templates...")
        init_examples(args.init)
        sys.exit(0)

    # Resolve paths before potential chdir
    task_file_path = None
    task_content = None

    if args.task_file:
        task_file_path = Path(args.task_file).resolve()
        if not task_file_path.exists():
            print(f"Error: Task file not found: {args.task_file}")
            sys.exit(1)
        task_content = task_file_path.read_text()

    if args.project:
        args.project = str(Path(args.project).resolve())

    # Set up working directory
    if args.working_dir:
        working_dir = Path(args.working_dir).resolve()
        working_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(working_dir)
    else:
        working_dir = Path.cwd()

    # Handle task content
    if args.task_file:
        pass  # Already loaded above
    elif args.task_input:
        task_content = args.task_input

    # Validations
    validate_packages(args.with_packages)
    validate_model(args.model)

    if not task_content and not args.interactive:
        print("Error: No task provided")
        print("\nUsage:")
        print('  coder "your task here"     # Inline task')
        print("  coder --task problem.md    # Task from file")
        print("  coder -i                   # Interactive mode")
        sys.exit(1)

    # Load project prompt
    project_prompt = load_project_prompt(args.project) if args.project else None

    # Run
    try:
        if args.interactive:
            run_interactive(
                working_dir, args.model, project_prompt, args.api_key, args.todo
            )
        else:
            # Use solve_task for the main flow
            if not args.quiet:
                if args.with_packages:
                    print(f"Dynamic packages: {', '.join(args.with_packages)}")
                print(f"Creating agent with model: {args.model or DEFAULT_MODEL}")

            task_basename = task_file_path.stem if task_file_path else None

            messages, stats, log_path = solve_task(
                task=task_content,
                working_directory=str(working_dir),
                model=args.model,
                project_prompt=project_prompt,
                with_packages=args.with_packages,
                api_key=args.api_key,
                todo=args.todo,
                quiet=args.quiet,
                save_log=True,
                task_basename=task_basename,
                step_limit=args.step_limit,
            )

            if not args.quiet:
                display_response(messages)
                display_statistics(stats)
                print(f"Log saved to: {log_path}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
