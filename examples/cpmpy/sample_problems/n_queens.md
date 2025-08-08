# N-Queens Problem

## Problem Description
Place N queens on an N×N chessboard such that no two queens threaten each other. A queen can attack any piece in the same row, column, or diagonal.

## Input Format
```python
n = 8  # Board size
```

## Output Format
Return a list of queen positions where position[i] represents the column of the queen in row i.

## Example
For n=4, one solution is:
```
. Q . .
. . . Q
Q . . .
. . Q .
```
Represented as: [1, 3, 0, 2]

## Constraints
- Use CPMPy for constraint modeling
- All queens must be placed
- No two queens can be on the same row (automatic from representation)
- No two queens can be on the same column
- No two queens can be on the same diagonal

## Test Cases
```python
# n=4: Should find solution like [1, 3, 0, 2]
# n=8: Should find one of 92 possible solutions
# n=1: Should return [0]
```