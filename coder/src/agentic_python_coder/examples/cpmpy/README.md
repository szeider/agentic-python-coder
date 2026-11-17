# CPMpy Examples

Constraint programming examples using CPMpy for solving combinatorial problems.

## Quick Start

Run these commands from the directory where `coder --init` was run (it creates `coder-examples/cpmpy/`). The solution is written to `<task>_code.py` in the current directory.

```bash
# Copy the template and sample tasks to coder-examples/cpmpy/
coder --init cpmpy

# Solve N-Queens
coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md --task coder-examples/cpmpy/sample_tasks/n_queens.md

# Solve Magic Square
coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md --task coder-examples/cpmpy/sample_tasks/magic_square.md
```

`--with cpmpy` starts the kernel in its own environment with CPMpy (uv installs it on first use). Without `--with`, the kernel runs the tool's own Python and sees only the tool's environment, so CPMpy installed elsewhere with `uv pip install` is not available to it.

## What's Included

The `cpmpy.md` project template provides:
- CPMpy constraint modeling patterns
- Common constraint types (AllDifferent, Sum, etc.)
- Solving strategies and optimization techniques

## Sample Problems

- **n_queens.md** - Place N queens on a chessboard
- **magic_square.md** - Create a magic square with equal sums

## Create Your Own

Write a markdown file with:
1. Problem description
2. Input format
3. Constraints to satisfy
4. Expected output format

Example:
```
# Sudoku Solver

## Problem
Fill a 9x9 grid with digits 1-9 following standard Sudoku rules.

## Input
Partial grid with 0 for empty cells

## Constraints
- Each row contains 1-9
- Each column contains 1-9
- Each 3x3 box contains 1-9

## Output
Completed grid
```

Then run:
```bash
coder --with cpmpy --project coder-examples/cpmpy/cpmpy.md --task your_problem.md
```

## Resources

- [CPMpy Documentation](https://cpmpy.readthedocs.io/)
- [CP-Bench Dataset](https://zenodo.org/records/15592407)