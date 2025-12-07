# CPMpy Examples

Constraint programming examples using CPMpy for solving combinatorial problems.

## Quick Start

```bash
# Recommended: Use --with flag (no installation needed)
coder --with cpmpy --project cpmpy.md n_queens.md

# Alternative: Install CPMpy manually first
uv pip install cpmpy

# Then solve N-Queens problem
cd sample_problems
coder --project ../cpmpy.md n_queens.md

# Solve Magic Square
coder --project ../cpmpy.md magic_square.md
```

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
coder --project cpmpy.md your_problem.md
```

## Resources

- [CPMpy Documentation](https://cpmpy.readthedocs.io/)
- [CP-Bench Dataset](https://zenodo.org/records/15592407)