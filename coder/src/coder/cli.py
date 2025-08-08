"""Command-line interface for the Python coding agent."""

import warnings
# Suppress specific warnings that are known and not problematic
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain")
warnings.filterwarnings("ignore", message=".*PythonREPL.*")

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, List, Any, Dict
from datetime import datetime

from coder.agent import create_coding_agent, run_agent
from coder.project_md import parse_project_file, check_packages_available, create_project_prompt
from coder.llm import MODEL_STRING


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
    parser = argparse.ArgumentParser(
        description="Coder - AI-powered Python coding assistant",
        usage="coder [task]"
    )
    
    parser.add_argument(
        "task",
        nargs="?",
        help="Task for the coder. If not provided, reads from task.md in current directory"
    )
    
    parser.add_argument(
        "--model",
        help=f"Model to use (default: {MODEL_STRING})"
    )
    
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Interactive mode"
    )
    
    parser.add_argument(
        "--project", "-p",
        help="Path to project markdown file with examples and available packages"
    )
    
    parser.add_argument(
        "--with",
        action="append",
        dest="with_packages",
        help="Additional packages to include (can be used multiple times, e.g., --with pandas --with numpy)"
    )
    
    args = parser.parse_args()
    
    # Validate package specifications if provided
    if args.with_packages:
        import re
        # Basic validation for package specs
        pattern = re.compile(
            r'^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?'  # Package name
            r'(\[[a-zA-Z0-9,_-]+\])?'  # Optional extras
            r'([@=!<>~]+[a-zA-Z0-9.*+!,\-_.]+)?$'  # Optional version spec
        )
        
        invalid_packages = []
        for pkg in args.with_packages:
            if not pattern.match(pkg):
                invalid_packages.append(pkg)
        
        if invalid_packages:
            print(f"❌ Error: Invalid package specifications: {', '.join(invalid_packages)}")
            print("Expected format: 'package' or 'package>=version' or 'package[extras]'")
            print("\nExamples:")
            print("  --with pandas")
            print("  --with 'numpy>=1.20'")
            print("  --with 'requests[security]'")
            sys.exit(1)
    
    # Determine working directory (always current directory)
    working_dir = Path.cwd()
    task_path = working_dir / "task.md"
    
    # Handle task
    if args.task:
        # Write task to file
        task_path.write_text(args.task)
        print(f"✅ Created task.md with your task")
    else:
        # Check if task.md exists
        if not task_path.exists():
            print("Error: No task provided and task.md not found in current directory")
            print("\nUsage:")
            print('  coder "your task here"  # Creates task.md and runs')
            print('  coder                   # Runs with existing task.md')
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
                    print(f"\n⚠️  Warning: The following packages are not installed:")
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
        run_coder(working_dir, args.model, args.interactive, project_prompt, args.with_packages)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def get_system_prompt_path() -> Path:
    """Get the path to the system prompt in the codebase."""
    # System prompt is in the coder package
    base_dir = Path(__file__).parent.parent.parent
    system_prompt_path = base_dir / "prompts" / "system.md"
    
    if not system_prompt_path.exists():
        raise FileNotFoundError(f"System prompt not found at: {system_prompt_path}")
    
    return system_prompt_path




def save_conversation_log(working_dir: Path, messages: List[Any], stats: Optional[Dict[str, Any]] = None):
    """Save conversation history and statistics to JSON file."""
    log_path = working_dir / "conversation_log.json"
    
    # Convert messages to serializable format
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "messages": []
    }
    
    for msg in messages:
        if hasattr(msg, "dict"):  # LangChain message
            msg_dict = msg.dict()
        elif isinstance(msg, dict):
            msg_dict = msg
        else:
            msg_dict = {"content": str(msg), "type": type(msg).__name__}
        
        log_data["messages"].append(msg_dict)
    
    # Add statistics if provided
    if stats:
        log_data["statistics"] = stats
    
    # Save to file
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)
    
    return log_path


def run_coder(working_dir: Path, model: Optional[str], interactive: bool, project_prompt: Optional[str] = None, with_packages: Optional[List[str]] = None):
    """Run the coder agent."""
    messages = []
    try:
        # Get system prompt from codebase
        system_prompt_path = get_system_prompt_path()
        
        # Get task path
        task_path = working_dir / "task.md"
        
        # Print info about dynamic mode if packages specified
        if with_packages:
            print(f"📦 Dynamic package mode with: {', '.join(with_packages)}")
        
        # Create agent
        print(f"🤖 Creating agent with model: {model or MODEL_STRING}")
        agent = create_coding_agent(
            working_directory=str(working_dir),
            system_prompt_path=str(system_prompt_path),
            task_prompt_path=str(task_path),
            model=model,
            project_prompt=project_prompt,
            with_packages=with_packages
        )
        
        if interactive:
            run_interactive(agent, working_dir, project_prompt)
        else:
            # Single run mode
            message = "Please complete the task described in the instructions."
            
            messages, stats = run_agent(agent, message)
            
            # Save conversation log with statistics
            log_path = save_conversation_log(working_dir, messages, stats)
            
            # Print the last assistant message
            for msg in reversed(messages):
                # Skip tool call messages
                has_tool_calls = False
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    has_tool_calls = True
                elif hasattr(msg, "additional_kwargs") and msg.additional_kwargs.get("tool_calls"):
                    has_tool_calls = True
                elif isinstance(msg, dict):
                    if msg.get("tool_calls") or msg.get("additional_kwargs", {}).get("tool_calls"):
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
                        if msg.get("content") and (msg.get("type") == "ai" or msg.get("role") == "assistant"):
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
            
            print(f"📄 Conversation saved to: {log_path}")
            
    except Exception as e:
        # Save partial conversation if available
        if messages:
            log_path = save_conversation_log(working_dir, messages)
            print(f"\n📄 Partial conversation saved to: {log_path}")
        raise


def run_interactive(agent, working_dir: Path, project_prompt: Optional[str] = None):
    """Run the agent in interactive mode."""
    print(f"\n🚀 Interactive mode - working in: {working_dir}")
    if project_prompt:
        print(f"📦 Project configuration loaded")
    print("Type 'exit' or 'quit' to stop.\n")
    
    thread_id = "interactive"
    all_messages = []
    cumulative_stats = {
        "tool_usage": {},
        "token_consumption": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        },
        "execution_time_seconds": 0
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
                    cumulative_stats["tool_usage"][tool] = cumulative_stats["tool_usage"].get(tool, 0) + count
                
                token_stats = stats.get("token_consumption", {})
                cumulative_stats["token_consumption"]["input_tokens"] += token_stats.get("input_tokens", 0)
                cumulative_stats["token_consumption"]["output_tokens"] += token_stats.get("output_tokens", 0)
                cumulative_stats["token_consumption"]["total_tokens"] += token_stats.get("total_tokens", 0)
                cumulative_stats["execution_time_seconds"] += stats.get("execution_time_seconds", 0)
                
                # Save after each interaction
                save_conversation_log(working_dir, all_messages, cumulative_stats)
                
                # Print the last assistant message
                for msg in reversed(messages):
                    # Skip tool call messages
                    has_tool_calls = False
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        has_tool_calls = True
                    elif hasattr(msg, "additional_kwargs") and msg.additional_kwargs.get("tool_calls"):
                        has_tool_calls = True
                    elif isinstance(msg, dict):
                        if msg.get("tool_calls") or msg.get("additional_kwargs", {}).get("tool_calls"):
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
                            if msg.get("content") and (msg.get("type") == "ai" or msg.get("role") == "assistant"):
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
            log_path = save_conversation_log(working_dir, all_messages, cumulative_stats)
            # Display final cumulative statistics
            if cumulative_stats and any(cumulative_stats.get("tool_usage", {}).values() or 
                                       cumulative_stats.get("token_consumption", {}).values()):
                print("\n📊 Session Summary:")
                display_statistics(cumulative_stats)
            print(f"📄 Conversation saved to: {log_path}")


if __name__ == "__main__":
    main()