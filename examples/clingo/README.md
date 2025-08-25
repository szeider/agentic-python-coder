# Answer Set Programming (ASP) with Clingo

This project template enables the Agentic Python Coder to solve combinatorial problems using Answer Set Programming (ASP) with the clingo Python API.

## What is ASP?

Answer Set Programming is a declarative programming paradigm for solving complex combinatorial search problems. It's particularly effective for:
- Constraint satisfaction problems
- Planning and scheduling
- Combinatorial optimization
- Knowledge representation with defaults and exceptions
- Diagnostic reasoning

## Usage

```bash
# Basic usage with clingo
coder --with clingo --project examples/clingo/clingo.md \
  "Solve the 4-queens problem"

# With a task file
coder --with clingo --project examples/clingo/clingo.md \
  --task examples/clingo/sample_tasks/bird_reasoning.md
```

## Sample Problems

The `sample_tasks/` directory contains example problems:

- **bird_reasoning.md** - Default reasoning with exceptions (showcases negation as failure)
- **diagnosis.md** - Circuit fault diagnosis (demonstrates abductive reasoning)
- **simple_coloring.md** - Graph coloring problem
- **sudoku_mini.md** - 4x4 Sudoku solver
- **stable_marriage.md** - Stable matching problem

## How It Works

1. The agent translates natural language problem descriptions into ASP rules
2. Uses clingo's Python API to solve the problem
3. Extracts and formats solutions as JSON
4. Handles optimization and multiple solutions

## Requirements

The clingo package is automatically installed when you use `--with clingo`.

## Example Output

For the bird reasoning problem, the agent will generate ASP rules like:
```asp
% Facts about creatures
bird(tweety).
penguin(opus).
ostrich(speedy).
eagle(eddie).

% Inheritance rules
bird(X) :- penguin(X).
bird(X) :- ostrich(X).
bird(X) :- eagle(X).

% Default rule: birds fly unless proven otherwise
flies(X) :- bird(X), not abnormal(X).

% Exceptions
abnormal(X) :- penguin(X).
abnormal(X) :- ostrich(X).
```

And produce solutions in JSON format:
```json
{
  "creatures": [
    {"name": "tweety", "flies": true, "reason": "bird - default"},
    {"name": "opus", "flies": false, "reason": "penguin - exception"},
    {"name": "eddie", "flies": true, "reason": "eagle - default"}
  ]
}
```

This showcases ASP's unique strength in handling default reasoning with exceptions through stable model semantics.