# Mini Sudoku Problem (4x4)

Solve this 4x4 Sudoku puzzle. Each row, column, and 2x2 box must contain the numbers 1-4 exactly once.

Given clues:
```
. 2 | 3 .
. . | . 2
----+----
3 . | . .
. 1 | 4 .
```

(dots represent empty cells)

Output format (JSON):
```json
{
  "solution": [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0]
  ]
}
```

(The zeros are placeholders; each entry of the answer is a number from 1 to 4.)

Note: The solution should be a 4x4 array where solution[row-1][col-1] gives the number at position (row, col).