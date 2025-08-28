# Agentic Python Coder

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![UV](https://img.shields.io/badge/Packaged%20with-UV-purple)](https://github.com/astral-sh/uv)
[![LangGraph](https://img.shields.io/badge/Built%20with-LangGraph-green)](https://github.com/langchain-ai/langgraph)

This is a Python coding agent that combines the ReAct (Reason and Act) framework with a persistent IPython kernel to solve programming tasks through iterative development. The system implements ReAct using LangGraph, maintains execution state via IPython for incremental code building, and provides file manipulation and task management tools. Domain-specific knowledge is injected through markdown project prompts rather than code changes, allowing adaptation to new problem areas including constraint programming (CPMpy), Answer Set Programming (Clingo), and text processing. The implementation spans approximately a few hundred lines of Python code. This architecture demonstrates that effective coding agents can be built with minimal complexity while maintaining practical capabilities for real-world programming tasks. 

For more details on the coder and particularly on its application to constraint modelling, see the paper [[Szeider 2025, arxiv-2508.07468]](https://arxiv.org/abs/2508.07468) (which refers to version 1.0.0 of this tool).

## Installation

### Prerequisites

- Python 3.11 or higher
- UV package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- OpenRouter API key from [openrouter.ai](https://openrouter.ai)

### Install

```bash
# Install coder globally
uv tool install agentic-python-coder

# Set up API key (one-time setup)
mkdir -p ~/.config/coder
echo 'OPENROUTER_API_KEY="your-key-here"' > ~/.config/coder/.env
```

## Quick Start

### Basic Usage

```bash
# Simple inline task (creates code.py and log.jsonl)
coder "Create a function that calculates factorial"

# Task from file (creates {basename}_code.py and {basename}.jsonl)
coder --task problem.md

# Specify working directory
coder --dir results/test1 "Calculate prime numbers"

# With external packages (dynamically installed)
coder --with pandas --with matplotlib "Load data.csv and create a bar chart"

# Override API key for testing
coder --api-key sk-or-test-key "Test task"
```

### Project Templates

Use domain-specific templates for better results:

```bash
# Regular expressions template
coder --project examples/regex/regex.md \
  "Extract all email addresses from: 'Contact info@example.com or sales@test.org'"

# Constraint programming with CPMpy
coder --with cpmpy --project examples/cpmpy/cpmpy.md \
  "Solve the 8-queens problem"

# Answer Set Programming with Clingo
coder --with clingo --project examples/clingo/clingo.md \
  "Model bird flight with default reasoning: birds fly except penguins"
```


## How It Works

1. You describe a task in natural language
2. The agent uses Claude Sonnet 4 to plan the approach
3. Code is written and executed in an IPython kernel
4. Errors are automatically detected and fixed
5. The solution is refined until it works

### Key Features

#### Output Files
- **Inline tasks**: Creates `code.py` and `log.jsonl`
- **File tasks**: Creates `{basename}_code.py` and `{basename}.jsonl`
- **Structured logs**: JSON Lines format for easy parsing and analysis

#### Working Directory Control
- Use `--dir` to specify working directory without changing current location
- Directories are created automatically if they don't exist
- Perfect for batch testing and parallel execution

#### Dynamic Package Installation
The `--with` flag enables dynamic package installation:
- UV creates temporary environments with specified packages
- No project dependencies or virtual environment needed
- Packages are cached for subsequent runs

#### API Key Management
- Default location: `~/.config/coder/.env` (one-time setup)
- Override with `--api-key` flag for testing or CI/CD
- No more copying `.env` files everywhere

## Examples

The `examples/` directory contains project templates:

- **regex/**: Pattern matching and text extraction
- **cpmpy/**: Constraint programming problems
- **clingo/**: Answer Set Programming for combinatorial problems

## Configuration

The agent looks for API key in this order:
1. `--api-key` command line flag (highest priority)
2. `~/.config/coder/.env` file (recommended)
3. `OPENROUTER_API_KEY` environment variable

Example `.env` file:
```
OPENROUTER_API_KEY="sk-or-v1-..."
```


## Security Notice

**This is experimental software.** The agent executes code automatically based on your instructions. For safety:
- Run the agent in a virtual machine or container when working with untrusted inputs
- The agent executes code in the working directory (current dir or `--dir` location)
- Consider using isolated environments for sensitive projects

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.