# Agentic Python Coder

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![UV](https://img.shields.io/badge/Packaged%20with-UV-purple)](https://github.com/astral-sh/uv)
[![LangGraph](https://img.shields.io/badge/Built%20with-LangGraph-green)](https://github.com/langchain-ai/langgraph)

A Python coding agent using the ReAct framework with a persistent IPython kernel. Works as a **CLI tool** or as a **Python library** for integration into your own applications.

For details on architecture and constraint modelling applications, see [[Szeider 2025, arxiv-2508.07468]](https://arxiv.org/abs/2508.07468).

## Installation

### Prerequisites

- Python 3.13
- UV package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- OpenRouter API key from [openrouter.ai](https://openrouter.ai)

### CLI Installation

```bash
# Install as CLI tool
uv tool install git+https://github.com/szeider/agentic-python-coder

# Set up API key
mkdir -p ~/.config/coder
echo 'OPENROUTER_API_KEY="your-key-here"' > ~/.config/coder/.env
```

### Library Installation

```bash
# Add to your project
uv add git+https://github.com/szeider/agentic-python-coder

# Or with pip
pip install git+https://github.com/szeider/agentic-python-coder
```

## Quick Start

### CLI Usage

```bash
# Simple task
coder "Create a function that calculates factorial"

# Task from file
coder --task problem.md

# With packages and project template
coder --with cpmpy --project examples/cpmpy/cpmpy.md "Solve 8-queens"
```

### Library Usage

```python
import agentic_python_coder as coder

# High-level: run a complete task
messages, stats, log_path = coder.solve_task(
    "Write a fibonacci function",
    working_directory="/tmp/workspace",
    model="sonnet",
    quiet=True,  # Suppress console output
)

# Get the final response
response = coder.get_final_response(messages)
print(response)
```

---

## API Reference

### `solve_task()` — High-Level API

Run a complete coding task end-to-end. Recommended for most use cases.

```python
from agentic_python_coder import solve_task

messages, stats, log_path = solve_task(
    task="Your task description",
    working_directory=".",           # Where to run and save files
    model=None,                      # Model alias: "sonnet", "opus", "deepseek", etc.
    system_prompt=None,              # Custom system prompt (string)
    system_prompt_path=None,         # Path to system prompt file
    project_prompt=None,             # Domain-specific context
    with_packages=None,              # ["pandas", "numpy"] for dynamic install
    api_key=None,                    # Override API key
    todo=False,                      # Enable todo_write tool
    quiet=False,                     # Suppress console output
    save_log=True,                   # Save conversation log
    task_basename=None,              # Base name for output files
    step_limit=None,                 # Max agent steps (default: 200)
)
```

**Returns:** `(messages, stats, log_path)`
- `messages`: List of agent messages
- `stats`: Dict with `tool_usage`, `token_consumption`, `execution_time_seconds`
- `log_path`: Path to saved log file (or None if `save_log=False`)

### `create_coding_agent()` / `run_agent()` — Low-Level API

For custom workflows, multi-turn conversations, or fine-grained control.

```python
from agentic_python_coder import create_coding_agent, run_agent, get_final_response

# Create agent
agent = create_coding_agent(
    working_directory="/tmp/workspace",
    system_prompt="You are a Python expert.",
    model="deepseek",
    with_packages=["pandas"],
)

# Run one or more turns
messages, stats = run_agent(agent, "Load data.csv", quiet=True)
messages2, stats2 = run_agent(agent, "Now plot column A", quiet=True)

# Extract response
print(get_final_response(messages2))
```

### `get_openrouter_llm()` — LLM Access

Get a configured LangChain LLM instance for custom use.

```python
from agentic_python_coder import get_openrouter_llm, MODEL_REGISTRY

# Get LLM by alias
llm = get_openrouter_llm(model="sonnet")

# See available models
print(MODEL_REGISTRY.keys())
# dict_keys(['deepseek', 'sonnet', 'opus', 'default', 'grok', 'qwen', 'gemini', 'gpt'])
```

---

## CLI Reference

### Basic Commands

```bash
# Inline task
coder "your task"

# Task from file (creates {basename}_code.py and {basename}.jsonl)
coder --task problem.md

# Specify working directory
coder --dir results/test1 "your task"

# Interactive mode
coder -i
```

### Options

| Flag | Description |
|------|-------------|
| `--version`, `-V` | Show version and exit |
| `--task`, `-t FILE` | Load task from markdown file |
| `--model MODEL` | Model to use (default: sonnet) |
| `--project`, `-p FILE` | Project template for domain-specific prompts |
| `--with PACKAGE` | Add packages dynamically (repeatable) |
| `--dir`, `-d DIR` | Working directory |
| `--api-key KEY` | Override API key |
| `--todo` | Enable task tracking tool |
| `--quiet`, `-q` | Suppress console output |
| `--step-limit N` | Max agent steps (default: 200) |
| `-i`, `--interactive` | Interactive conversation mode |

### Model Selection

```bash
coder --model sonnet "task"     # Claude Sonnet 4.5 (default)
coder --model opus "task"       # Claude Opus 4.5
coder --model deepseek "task"   # DeepSeek v3.1
coder --model grok "task"       # X.AI Grok
coder --model qwen "task"       # Qwen3 Coder
coder --model gemini "task"     # Gemini Pro 2.5
coder --model gpt "task"        # GPT-5
```

### Project Templates

Domain-specific templates improve results:

```bash
# Constraint programming
coder --with cpmpy --project examples/cpmpy/cpmpy.md "Solve 8-queens"

# Answer Set Programming
coder --with clingo --project examples/clingo/clingo.md "Model bird flight"
```

### Interactive Mode

Interactive mode (`-i`) maintains a persistent session for multi-turn conversations:

```bash
# Start interactive session
coder -i

# With project template
coder -i --project examples/cpmpy/cpmpy.md --with cpmpy
```

**Features:**
- Persistent IPython kernel (state preserved across turns)
- Type `exit` or `quit` to end session
- Cumulative statistics shown on exit
- Conversation log saved to `log.jsonl`

**Example session:**
```
$ coder -i
Interactive mode - working in: /path/to/dir
Type 'exit' or 'quit' to stop.

You: Load data.csv and show the columns
Agent working...
[Agent loads file, displays columns]

You: Plot the 'sales' column
Agent working...
[Agent creates plot using existing dataframe]

You: exit
Goodbye!
Log saved to: log.jsonl
```

---

## Configuration

### API Key

The agent looks for API key in order:
1. `--api-key` flag or `api_key` parameter
2. `~/.config/coder/.env` file
3. `OPENROUTER_API_KEY` environment variable

```bash
# Recommended: one-time setup
mkdir -p ~/.config/coder
echo 'OPENROUTER_API_KEY="sk-or-v1-..."' > ~/.config/coder/.env
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | API key for OpenRouter |
| `CODER_VERBOSE` | Show detailed model configuration |
| `CODER_WITH_PACKAGES` | Comma-separated packages (internal use) |

---

## How It Works

1. Task is parsed and sent to the LLM
2. Agent reasons about approach using ReAct framework
3. Code executes in persistent IPython kernel (state preserved)
4. Errors detected and fixed automatically
5. Solution refined until complete

### Output Files

- **Inline tasks**: `solution.py` + `log.jsonl`
- **File tasks**: `{basename}_code.py` + `{basename}.jsonl`

---

## Security Notice

**This is experimental software.** The agent executes code automatically.

- Run in a VM or container for untrusted inputs
- Code executes in the working directory
- Use isolated environments for sensitive projects

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
