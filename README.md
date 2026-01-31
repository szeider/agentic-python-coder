# Agentic Python Coder

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![UV](https://img.shields.io/badge/Packaged%20with-UV-purple)](https://github.com/astral-sh/uv)

This package provides two utilities for Python code execution:

1. **coder** — An autonomous coding agent using the ReAct pattern (CLI + Python library)
2. **ipython_mcp** — An MCP server that gives any MCP-compatible client (Claude Desktop, etc.) Python execution capability

Both share a persistent IPython kernel for stateful code execution.

For details on architecture and constraint modelling applications, see [[Szeider 2025, arxiv-2508.07468]](https://arxiv.org/abs/2508.07468).

## Installation

### Prerequisites

- Python 3.13
- UV package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### For the Coding Agent

```bash
# Install as CLI tool
uv tool install agentic-python-coder

# Set up OpenRouter API key
mkdir -p ~/.config/coder
echo 'OPENROUTER_API_KEY="your-key-here"' > ~/.config/coder/.env
```

Get your API key from [openrouter.ai](https://openrouter.ai).

### For the MCP Server

No installation required — use `uvx` to run directly. See [MCP Server Configuration](#mcp-server-configuration).

---

## Quick Start

### Option A: Autonomous Agent

```bash
# Simple task
coder "Create a function that calculates factorial"

# With packages and project template
coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md "Solve 8-queens"

# Interactive mode
coder -i
```

### Option B: MCP Server

Add to your Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "ipython": {
      "command": "uvx",
      "args": ["--from", "agentic-python-coder", "ipython_mcp"]
    }
  }
}
```

Then ask Claude Desktop to execute Python code — it will use the persistent IPython session.

---

## The Coding Agent

### CLI Usage

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

### CLI Options

| Flag | Description |
|------|-------------|
| `--version`, `-V` | Show version and exit |
| `--init [TEMPLATE]` | Initialize example templates (cpmpy, clingo, regex, or all) |
| `--task`, `-t FILE` | Load task from markdown file |
| `--model MODEL` | Model name or JSON file (default: sonnet45) |
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
# Built-in models (versioned names)
coder --model sonnet45 "task"   # Claude Sonnet 4.5 (default)
coder --model opus45 "task"     # Claude Opus 4.5
coder --model deepseek31 "task" # DeepSeek v3.1
coder --model grok41 "task"     # X.AI Grok 4.1
coder --model qwen3 "task"      # Qwen3 Coder
coder --model gemini25 "task"     # Gemini Pro 2.5
coder --model gemini3pro "task"  # Gemini 3 Pro Preview
coder --model gpt52 "task"       # GPT-5.2

# Custom model (JSON file)
coder --model ./mymodel.json "task"
```

### Project Templates

Domain-specific templates improve results. Bundled examples are available on GitHub at [`coder/src/agentic_python_coder/examples/`](coder/src/agentic_python_coder/examples/). Use `--init` to copy them locally:

```bash
# Copy all bundled examples to coder-examples/
coder --init

# Or copy a specific template
coder --init cpmpy

# Then use with your task
coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md "Solve 8-queens"
coder --with clingo --project coder-examples/clingo/clingo.md "Model bird flight"
```

### Interactive Mode

Interactive mode (`-i`) maintains a persistent session for multi-turn conversations:

```bash
coder -i --project coder-examples/cpmpy/cpmpy.md --with cpmpy
```

State is preserved across turns. Type `exit` or `quit` to end.

### Library Usage

```python
import agentic_python_coder as coder

# High-level: run a complete task
messages, stats, log_path = coder.solve_task(
    "Write a fibonacci function",
    working_directory="/tmp/workspace",
    model="sonnet45",
    quiet=True,
)

# Get the final response
response = coder.get_final_response(messages)
print(response)
```

### Library API Reference

#### `solve_task()` — High-Level API

```python
from agentic_python_coder import solve_task

messages, stats, log_path = solve_task(
    task="Your task description",
    working_directory=".",           # Where to run and save files
    model=None,                      # Model name: "sonnet45", "opus45", or JSON file
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

#### `create_coding_agent()` / `run_agent()` — Low-Level API

```python
from agentic_python_coder import create_coding_agent, run_agent, get_final_response

# Create agent
agent = create_coding_agent(
    working_directory="/tmp/workspace",
    system_prompt="You are a Python expert.",
    model="deepseek31",
    with_packages=["pandas"],
)

# Run one or more turns
messages, stats = run_agent(agent, "Load data.csv", quiet=True)
messages2, stats2 = run_agent(agent, "Now plot column A", quiet=True)

print(get_final_response(messages2))
```

#### `get_openrouter_llm()` — LLM Access

```python
from agentic_python_coder import get_openrouter_llm, list_available_models

llm = get_openrouter_llm(model="sonnet45")
print(list_available_models())
# ['deepseek31', 'gemini25', 'gemini3pro', 'gpt52', 'grok41', 'opus45', 'qwen3', 'sonnet45']
```

---

## The MCP Server

The `ipython_mcp` server provides Python code execution via the Model Context Protocol. Use it to give Claude Desktop (or any MCP-compatible client) the ability to run Python code in a persistent session.

### MCP Server Configuration

Add to your MCP settings (e.g., `~/.claude/claude_desktop_config.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "ipython": {
      "command": "uvx",
      "args": ["--from", "agentic-python-coder", "ipython_mcp"]
    }
  }
}
```

### Available Tools

| Tool | Description |
|------|-------------|
| `python_exec` | Execute Python code. Auto-starts session if needed. Default 30s timeout. |
| `python_reset` | Create new kernel (no `kernel_id`) OR reset existing kernel (with `kernel_id`). Optionally install packages. |
| `python_status` | Check session state: active flag, all active kernel IDs, Python version, packages, variables. |
| `python_interrupt` | Send interrupt signal to stop long-running code. Session state is preserved. |

### Multi-Agent Workflow

For parallel agents, each agent gets its own kernel:

```
Agent A                              Agent B
────────                             ────────
python_reset() → kernel_id="aaa"     python_reset() → kernel_id="bbb"
python_exec(kernel_id="aaa", ...)    python_exec(kernel_id="bbb", ...)
python_exec(kernel_id="aaa", ...)    python_exec(kernel_id="bbb", ...)
```

Simple single-agent use: just call `python_exec()` — the default kernel auto-starts.

### Features

- **Persistent state**: Variables, imports, and definitions persist across executions
- **Auto-start**: Default session starts automatically on first `python_exec`
- **Package installation**: Use `python_reset` with `packages` parameter to install dependencies
- **Timeout handling**: Long-running code times out gracefully (session preserved)
- **Interrupt support**: Stop runaway code without losing session state
- **Multi-kernel**: Each `python_reset()` creates an isolated kernel for parallel agents

### Usage Tips

When using the MCP server for domain-specific tasks (constraint programming, ASP, etc.), provide the project template content directly in your conversation. For example, paste the contents of `coder-examples/cpmpy/cpmpy.md` when working with CPMpy.

---

## Configuration

### API Key (Coding Agent only)

The coding agent requires an OpenRouter API key. It looks in order:
1. `--api-key` flag or `api_key` parameter
2. `~/.config/coder/.env` file
3. `OPENROUTER_API_KEY` environment variable

```bash
mkdir -p ~/.config/coder
echo 'OPENROUTER_API_KEY="sk-or-v1-..."' > ~/.config/coder/.env
```

The MCP server does not require an API key — it only executes code.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | API key for OpenRouter (agent only) |
| `CODER_VERBOSE` | Show detailed model configuration |

---

## Security Notice

**This is experimental software.** Both the coding agent and MCP server execute code automatically.

- Run in a VM or container for untrusted inputs
- Code executes in the working directory
- Use isolated environments for sensitive projects

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
