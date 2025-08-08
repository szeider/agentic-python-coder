# Agentic Python Coder

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![UV](https://img.shields.io/badge/Packaged%20with-UV-purple)](https://github.com/astral-sh/uv)
[![LangGraph](https://img.shields.io/badge/Built%20with-LangGraph-green)](https://github.com/langchain-ai/langgraph)

This is a Python coding agent that combines the ReAct (Reason and Act) framework with a persistent IPython kernel to solve programming tasks through iterative development. The system implements ReAct using LangGraph, maintains execution state via IPython for incremental code building, and provides file manipulation and task management tools. Domain-specific knowledge is injected through markdown project prompts rather than code changes, allowing adaptation to new problem areas such as constraint programming or text processing. The implementation spans approximately a few hundred lines of Python code. This architecture demonstrates that effective coding agents can be built with minimal complexity while maintaining practical capabilities for real-world programming tasks.

## Installation

### Prerequisites

- Python 3.11 or higher
- UV package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- OpenRouter API key from [openrouter.ai](https://openrouter.ai)

### Install

```bash
# Install coder globally
uv tool install agentic-python-coder

# Create a .env file with your API key
echo 'OPENROUTER_API_KEY="your-key-here"' > .env
```

## Quick Start

### Basic Usage

```bash
# Simple task
coder "Create a function that calculates factorial"

# With external packages (dynamically installed)
coder --with pandas --with matplotlib "Load data.csv and create a bar chart"
```

### Project Templates

Use domain-specific templates for better results:

```bash
# Regular expressions template
coder --project examples/regex/regex.md \
  "Extract all email addresses from: 'Contact info@example.com or sales@test.org'"

# Constraint programming (requires cpmpy)
coder --with cpmpy --project examples/cpmpy/cpmpy.md \
  "Solve the 8-queens problem"
```

## How It Works

1. You describe a task in natural language
2. The agent uses Claude Sonnet 4 to plan the approach
3. Code is written and executed in an IPython kernel
4. Errors are automatically detected and fixed
5. The solution is refined until it works

### Dynamic Package Mode

The `--with` flag enables dynamic package installation:
- UV creates temporary environments with specified packages
- No project dependencies or virtual environment needed
- Packages are cached for subsequent runs

## Examples

The `examples/` directory contains project templates:

- **regex/**: Pattern matching and text extraction
- **cpmpy/**: Constraint programming problems

## Configuration

The agent looks for `.env` file in the current directory:

```
OPENROUTER_API_KEY="your-key-here"
```

## Security Notice

**This is experimental software.** The agent executes code automatically based on your instructions. For safety:
- Run the agent in a virtual machine or container when working with untrusted inputs
- Be aware that the agent can read, write, and execute files in the current directory
- Consider using isolated environments for sensitive projects

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.