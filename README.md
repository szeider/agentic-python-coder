# Agentic Python Coder

[![Python 3.13](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![UV](https://img.shields.io/badge/Packaged%20with-UV-purple)](https://github.com/astral-sh/uv)

This package provides two utilities for Python code execution:

1. **coder** — An autonomous coding agent using the ReAct pattern (CLI + Python library). It calls an LLM through OpenRouter or another OpenAI-compatible endpoint that supports tool calling on Chat Completions.
2. **ipython_mcp** — An MCP server that gives any MCP-compatible client (Claude Desktop, Claude Code, etc.) Python execution capability

Both run code in persistent IPython kernels, so variables, imports and definitions survive from one call to the next.

Get started: [install the coding agent](#for-the-coding-agent) or [configure the MCP server](#option-b-mcp-server).

For the architecture and its application to constraint modeling, see Stefan Szeider, "CP-Agent: Agentic Constraint Programming", LLM4Code 2026 ([DOI 10.1145/3786181.3788711](https://doi.org/10.1145/3786181.3788711), [arXiv:2508.07468](https://arxiv.org/abs/2508.07468)).

## Used by MCP Solver

[MCP Solver](https://github.com/szeider/mcp-solver) (PyPI package [`agentic-mcp-solver`](https://pypi.org/project/agentic-mcp-solver/)) is built on this package. Its MCP server (`mcp-solver-serve`) and its CLI (`mcp-solver`) both start `ipython_mcp` as their kernel engine and talk to it over stdio; the CLI also resolves model aliases with this package's `load_model_config`. On top of the kernel tools, MCP Solver adds solver backends (PySAT, MaxSAT, Z3, CPMpy, Clingo, DIDP) with their modeling instructions. Its CLI agent is [mcp-minion](https://pypi.org/project/mcp-minion/), a minimal ReAct agent over MCP that is developed in the MCP Solver repository and can also be pointed at `ipython_mcp` directly. MCP Solver releases up to 4.4.x require agentic-python-coder below 4; support for 4.x comes with the MCP Solver release that follows.

## Installation

### Prerequisites

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`. Kernels started with packages (`coder --with`, `python_reset(packages=[...])`) are launched by uv and need uv 0.4.30 or newer.

The commands below pin `--python 3.14`: uv otherwise picks the newest installed Python, kernels with packages run on the same Python version as the tool, and ortools (used by cpmpy) has no 3.15 wheels yet.

### For the Coding Agent

```bash
# Install as CLI tool
uv tool install --python 3.14 agentic-python-coder

# Set up OpenRouter API key
mkdir -p ~/.config/coder
echo 'OPENROUTER_API_KEY="your-key-here"' > ~/.config/coder/.env
```

Get your API key from [openrouter.ai](https://openrouter.ai). See [API Key](#api-key-coding-agent-only) for the lookup order.

### For the MCP Server

No installation required — use `uvx` to run directly. See [MCP Server Configuration](#mcp-server-configuration).

---

## Quick Start

### Option A: Autonomous Agent

```bash
# Simple task (writes log.jsonl, and solution.py if the agent saves its code)
coder "Create a function that calculates factorial"

# With packages and a project template (copy the bundled templates first)
coder --init cpmpy
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
      "args": ["--python", "3.14", "--from", "agentic-python-coder", "ipython_mcp"]
    }
  }
}
```

Then ask Claude Desktop to execute Python code — it will use the persistent IPython session.

---

## The Coding Agent

### CLI Usage

See [Quick Start](#quick-start) for inline tasks and interactive mode.

```bash
# Task from file (writes problem.jsonl, and problem_code.py if the agent saves its code)
coder --task problem.md

# Specify working directory
coder --dir results/test1 "your task"
```

The log is written on every run; it records tool calls, their success or error, and statistics, not the full conversation. The code file is written only when the agent calls its `save_code` tool with code that compiles.

### CLI Options

| Flag | Description |
|------|-------------|
| `--version`, `-V` | Show version and exit |
| `--init [TEMPLATE]` | Initialize example templates (cpmpy, clingo, regex, or all) |
| `--task`, `-t FILE` | Load task from markdown file |
| `--model MODEL` | Model name or JSON file (default: sonnet55) |
| `--project`, `-p FILE` | Project template for domain-specific prompts |
| `--with PACKAGE` | Package for the kernel (repeatable); the kernel then runs in an isolated environment with only these packages (see [Kernels](#kernels)) |
| `--dir`, `-d DIR` | Working directory |
| `--api-key KEY` | Override API key |
| `--todo` | Enable task tracking tool |
| `--quiet`, `-q` | Suppress agent progress, final response and statistics (setup messages still appear); ignored with `-i` |
| `--step-limit N` | Max agent steps (default: 200); ignored with `-i`, which allows 200 steps per turn |
| `-i`, `--interactive` | Interactive conversation mode |

### Project Templates

A project template adds domain-specific instructions and examples to the agent's prompt. Bundled examples are available on GitHub at [`coder/src/agentic_python_coder/examples/`](https://github.com/szeider/agentic-python-coder/tree/main/coder/src/agentic_python_coder/examples). Use `--init` to copy them locally:

```bash
# Copy all bundled examples to coder-examples/
coder --init

# Or copy a specific template
coder --init cpmpy

# Then use with your task
coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md "Solve 8-queens"
coder --with clingo --project coder-examples/clingo/clingo.md "Model bird flight"
```

Each template folder contains the template (`cpmpy.md`, `clingo.md`, `regex.md`), a README and sample tasks in `sample_tasks/`, for example `coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md --task coder-examples/cpmpy/sample_tasks/n_queens.md`.

### Interactive Mode

Interactive mode (`-i`) maintains a persistent session for multi-turn conversations:

```bash
coder -i --project coder-examples/cpmpy/cpmpy.md --with cpmpy
```

Tasks are typed at the `You:` prompt; a task given on the command line or with `--task` is not used. State is preserved across turns. Type `exit` or `quit` to end.

### Model Selection

```bash
coder --model opus55 "task"            # a bundled model alias
coder --model ./mymodel.json "task"    # a custom model JSON file
```

Bundled aliases (`list_available_models()` returns the same list); all run through OpenRouter:

| Alias | OpenRouter model id |
|-------|---------------------|
| `sonnet55` (default) | `anthropic/claude-sonnet-5.5` |
| `sonnet5` | `anthropic/claude-sonnet-5` |
| `sonnet46` | `anthropic/claude-sonnet-4.6` |
| `sonnet45` | `anthropic/claude-sonnet-4.5` |
| `opus55` | `anthropic/claude-opus-5.5` |
| `opus48` | `anthropic/claude-opus-4.8` |
| `opus45` | `anthropic/claude-opus-4.5` |
| `gpt6astra` | `openai/gpt-6-astra` |
| `gpt6sol` | `openai/gpt-6-sol` |
| `gpt56sol` | `openai/gpt-5.6-sol` |
| `gpt56terra` | `openai/gpt-5.6-terra` |
| `gpt52` | `openai/gpt-5.2` |
| `gemini4argon` | `google/gemini-4-argon` |
| `gemini31` | `google/gemini-3.1-pro-preview` |
| `gemini3flash` | `google/gemini-3-flash-preview` |
| `gemini25` | `google/gemini-2.5-pro` |
| `grok47` | `x-ai/grok-4.7` |
| `deepseek31` | `deepseek/deepseek-chat-v3.1` |
| `qwen3` | `qwen/qwen3-coder` |

A `--model` value that ends in `.json` is a file path; a relative path is resolved against the working directory (`--dir`). Any other value is looked up first as `./NAME.json` in the working directory, then among the bundled aliases.

### Custom Models and Endpoints

A model JSON can use any OpenRouter model id or point at another OpenAI-compatible endpoint that supports tool calling on Chat Completions. OpenAI directly:

```json
{
  "path": "gpt-6-luna",
  "base_url": "https://api.openai.com/v1",
  "api_key_env": "OPENAI_API_KEY",
  "reasoning_effort": "none"
}
```

OpenAI documents tool calling on the Chat Completions endpoint for this model with reasoning effort `none`, and a model that offers tool calling only through the Responses API cannot be used.

A local Ollama server:

```json
{
  "path": "your-model",
  "base_url": "http://localhost:11434/v1",
  "api_key_env": "OLLAMA_API_KEY",
  "request_timeout": 600
}
```

Replace `your-model` by the name of a model installed in Ollama that supports tool calling. Ollama ignores the key, but the variable must be set (for example `export OLLAMA_API_KEY=ollama`) or `--api-key` given.

| Field | Meaning |
|-------|---------|
| `path` | Model id sent to the endpoint (required) |
| `base_url` | OpenAI-compatible endpoint (default: `https://openrouter.ai/api/v1`) |
| `api_key_env` | Name of the environment variable that holds the key for this endpoint. It is read from the environment only, not from `~/.config/coder/.env`; if it is not set, the run stops with an error. Without `api_key_env` the OpenRouter key is used, also for a custom `base_url`, so set it for every non-OpenRouter endpoint. |
| `request_timeout` | Client timeout in seconds |
| `temperature`, `max_tokens`, `top_p`, `frequency_penalty`, `presence_penalty`, `top_k` | Sampling parameters, sent only when present in the file (`top_k` in the request body) |
| `no_sampling_params` | `true`: of the sampling parameters only `max_tokens` is sent (for models that reject them); the fields below are not affected |
| `provider`, `reasoning` | OpenRouter options (routing, reasoning tokens), sent in the request body when present |
| `reasoning_effort` | Sent as the top-level `reasoning_effort` request parameter when present (for example `"none"` for OpenAI) |

`--api-key` (or `api_key=`) takes precedence over `api_key_env`.

---

## The MCP Server

The `ipython_mcp` server provides Python code execution via the Model Context Protocol. Use it to give Claude Desktop, Claude Code or any other MCP client the ability to run Python code in a persistent session. It needs no API key.

### MCP Server Configuration

Use the JSON from [Option B](#option-b-mcp-server) in the client's MCP settings: for Claude Desktop, `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`); for Claude Code, a project `.mcp.json`, or add it from the command line:

```bash
claude mcp add ipython -- uvx --python 3.14 --from agentic-python-coder ipython_mcp
```

### Available Tools

| Tool | Description |
|------|-------------|
| `python_exec` | Execute Python code (`code`, optional `timeout`: default 30 s, max 300 s). Starts the default kernel if it is not running. |
| `python_reset` | Restart a kernel with a clean state, optionally with `packages`. Without `kernel_id`: the default kernel. With `kernel_id`: that kernel, created if the id has neither a kernel nor a crash record (`"created": true`). |
| `python_status` | Kernel state without side effects: `active`, `all_kernels` (live kernel ids), `python_version`, `packages` (requested ones first, at most 20), `packages_total`, `variables`, `kernel_busy`, `crashed`. |
| `python_interrupt` | Send an interrupt (like Ctrl+C) to running code. The state is kept unless the kernel dies. |
| `submit_code` | Submit the final standalone program (`code`). Syntax-checked with `compile()`, not executed or saved; returns `{"ok": true}` or `{"ok": false, "error": ...}`. |

### Kernels

Every kernel tool called without `kernel_id` uses the default kernel `_default`, which starts on the first `python_exec` or `python_reset`; `submit_code` uses no kernel. A separate kernel is created by `python_reset` with an id of your choice (1 to 64 letters, digits, `_`, `-`, `.`, starting with a letter or digit; `default`, `new`, `none`, `null` in any case and ids starting with `_` are reserved, except `_default`, which names the default kernel). Pass the same `kernel_id` on every later call. A session, with replies shortened:

```
python_exec(code="x = 41; x + 1")                  → {"success": true, "result": "42", "kernel_id": "_default"}
python_reset(kernel_id="a-1", packages=["six"])    → {"success": true, "kernel_id": "a-1", "created": true}
python_exec(kernel_id="a-1", code="x")             → error: name 'x' is not defined (separate state)
python_exec(kernel_id="a-1", code="import yaml")   → error: No module named 'yaml' (only six and its dependencies)
python_exec(kernel_id="b-9", code="1")             → error: Kernel "b-9" not found. Live kernels: ["_default", "a-1"]. ...
```

- `python_reset` with a known id restarts that kernel (`"created": false`). The same call works on first use, to clear state, and after a crash.
- `packages`: a non-empty list replaces the kernel's packages; omitted, `null` or `[]` keeps them.
- A kernel with packages can import only those packages, their dependencies, ipykernel and the standard library: uv starts it in an isolated environment on the server's Python version that ignores the server's virtual environment, `VIRTUAL_ENV`, a `.venv` in the working directory and `PYTHONPATH` (uv 0.4.30 or newer). A kernel without packages runs the server's own Python and sees its environment.
- Package isolation controls which packages a kernel can import. It does not restrict access to files, the network or credentials; use a VM or container for untrusted code (see [Security Notice](#security-notice)).
- `python_exec`, `python_status` and `python_interrupt` never create a named kernel. For an unknown id, `python_exec` and `python_interrupt` return an error that lists the live kernels, and `python_status` returns `"active": false`.
- If the default kernel crashed, the next `python_exec` restarts it with the same packages but does not run its code: the reply is an error with `"kernel_restarted": true` and `"executed": false`, and the code must be sent again. Earlier variables and imports are gone. A crashed named kernel is restarted by `python_reset(kernel_id=...)`. A restart of the server process loses all kernels and their packages; the next `python_exec` then starts a bare default kernel without this signal.
- Code runs non-interactively: `input()` raises an error, and replies carry text only (matplotlib uses the Agg backend), so save plots to files.
- All clients of one server process that omit `kernel_id` share the default kernel, and two clients that pick the same name share that kernel. Parallel agents keep their state apart by each using its own `kernel_id`.
- `CODER_MAX_KERNELS` (default 10) limits the named kernels; the default kernel does not count.

### Replies

- `python_exec` returns `success`, `kernel_id`, `stdout`, `stderr`, `result` (IPython's text representation of the last expression, or `null`) and `error`. Each of the four text fields is cut after 102,400 characters with a note. Errors raised before the code runs (unknown or crashed kernel) and the reply to empty code omit some of these fields.
- On a timeout the server interrupts the code and waits up to 2 s. If the kernel survives, the reply has `"timed_out": true`. If the code stopped, `"kernel_busy": false` and the state is kept. If the code ignores the interrupt, `"kernel_busy": true`: the kernel takes no new code until it ends; `python_interrupt` tries again, and `python_reset` ends it (the reply then has `"replaced_busy_kernel": true`). If the kernel died, the reply is a crash error without these keys.
- A `python_exec` that arrives while another call runs on the same kernel waits for it within its own timeout. It is refused with `"executed": false` and `"kernel_busy": true` if that wait runs out or if code abandoned after a timeout is still running; `python_status` shows `kernel_busy` without running anything in the kernel.
- `python_reset` returns `success`, `kernel_id`, `message` (with the package versions when they can be read) and `created`; a failed reset returns `success: false`, `kernel_id` and `error`.

The full list of changes, with the exact texts, is in the [CHANGELOG](https://github.com/szeider/agentic-python-coder/blob/main/CHANGELOG.md).

### Usage Tips

When using the MCP server for domain-specific tasks (constraint programming, ASP, etc.), provide the project template content directly in your conversation. For example, paste the contents of `coder-examples/cpmpy/cpmpy.md` (from `coder --init`) when working with CPMpy, and have the client call `python_reset(packages=["cpmpy"])` first: a pasted template installs nothing.

---

## Library Usage

Install the package into your application's environment (Python 3.13 or newer): `uv add agentic-python-coder`, or `pip install agentic-python-coder` in an existing environment. `with_packages` needs uv (see [Prerequisites](#prerequisites)).

```python
import agentic_python_coder as coder

# High-level: run a complete task
messages, stats, log_path = coder.solve_task(
    "Write a fibonacci function",
    working_directory="/tmp/workspace",
    model="sonnet55",
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
    model=None,                      # Model alias ("sonnet55", "opus55", ...) or JSON file; None: sonnet55
    system_prompt=None,              # Custom system prompt (string)
    system_prompt_path=None,         # Path to system prompt file
    project_prompt=None,             # Domain-specific context
    with_packages=None,              # ["pandas", "numpy"]: isolated kernel with only these packages
    api_key=None,                    # Override API key
    todo=False,                      # Enable todo_write tool
    quiet=False,                     # Suppress console output
    save_log=True,                   # Write the JSONL event log
    task_basename=None,              # Base name for output files
    step_limit=None,                 # Max agent steps (default: 200)
    llm_config=None,                 # Pre-built LLMConfig (overrides model/api_key)
)
```

**Returns:** `(messages, stats, log_path)`
- `messages`: List of agent messages (the full conversation)
- `stats`: Dict with `tool_usage`, `token_consumption`, `execution_time_seconds` (and `step_limit_reached` when the step limit was hit)
- `log_path`: Path to the event log described under [CLI Usage](#cli-usage) (None if `save_log=False`)

#### `create_coding_agent()` / `run_agent()` — Low-Level API

```python
from pathlib import Path
from agentic_python_coder import create_coding_agent, run_agent, get_final_response

# Unlike solve_task, create_coding_agent does not create the directory
Path("/tmp/workspace").mkdir(parents=True, exist_ok=True)  # put data.csv here

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

Instead of a model name, you can pass a pre-built `LLMConfig` wrapping an
OpenAI client for an endpoint that supports tool calling on Chat Completions;
`api_params` is passed to every `chat.completions.create` call:

```python
import os
from openai import OpenAI
from agentic_python_coder import LLMConfig, create_coding_agent

llm_config = LLMConfig(
    client=OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url="https://api.openai.com/v1"),
    model="gpt-6-luna",
    api_params={"reasoning_effort": "none"},
)

agent = create_coding_agent(
    working_directory="/tmp/workspace",
    llm_config=llm_config,
)
```

#### `get_openrouter_llm()` — LLM Access

```python
from agentic_python_coder import get_openrouter_llm, list_available_models

llm = get_openrouter_llm(model="sonnet55")
print(list_available_models())
# ['deepseek31', 'gemini25', 'gemini31', 'gemini3flash', 'gemini4argon', ...]
```

---

## Configuration

### API Key (Coding Agent only)

The coding agent needs an OpenRouter API key, unless the model JSON names its own key with `api_key_env` (see [Custom Models and Endpoints](#custom-models-and-endpoints)). It looks in order:
1. `--api-key` flag or `api_key` parameter
2. `OPENROUTER_API_KEY` environment variable
3. `OPENROUTER_API_KEY` in `~/.config/coder/.env` (see [Installation](#for-the-coding-agent))

The MCP server does not require an API key — it only executes code.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | API key for OpenRouter (agent only) |
| `CODER_VERBOSE` | With verbose output enabled, any nonempty value prints more of the model configuration |
| `CODER_MAX_KERNELS` | Maximum number of named kernels of the MCP server (default 10) |
| `CODER_LOG_LEVEL` | Log level of the kernel manager (default `WARNING`) |

---

## Development

```bash
git clone https://github.com/szeider/agentic-python-coder.git
cd agentic-python-coder
uv run --project . coder --help                        # run the CLI from the checkout
uv run --project . --extra test pytest coder/tests/    # tests (network tests excluded)
uv run --project . --extra test pytest -m network coder/tests/   # tests that call the network
```

Changes per release are listed in the [CHANGELOG](https://github.com/szeider/agentic-python-coder/blob/main/CHANGELOG.md).

---

## Security Notice

**This is experimental software.** Both the coding agent and MCP server execute code automatically.

- Executed code runs with your user's permissions. The working directory is not a boundary: the code can read and write other files, use the network and read inherited environment variables such as API keys.
- Package isolation (`--with`, `with_packages`, `python_reset(packages=...)`) controls only which packages a kernel can import; it is not a sandbox.
- Run in a VM or container for untrusted code or inputs.

## License

Apache License 2.0 - see [LICENSE](https://github.com/szeider/agentic-python-coder/blob/main/LICENSE) for details.
