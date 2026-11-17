# Magic Square Problem

## Problem Description
Fill an n×n grid with distinct integers from 1 to n² such that the sum of numbers in each row, column, and both main diagonals equals the same "magic constant".

## Input Format
```python
n = 3  # Size of the square
```

## Magic Constant
For an n×n magic square using numbers 1 to n², the magic constant is:
```
magic_constant = n * (n² + 1) / 2
```

## Output Format
Return a 2D array representing the magic square.

## Example
For n=3, the output has this shape (placeholder letters stand for the numbers 1 to 9):
```
a b c
d e f
g h i
```
Each row, column, and diagonal must sum to 15.

## Constraints
- Use CPMPy for constraint modeling
- All numbers from 1 to n² must be used exactly once
- All rows must sum to the magic constant
- All columns must sum to the magic constant
- Both diagonals must sum to the magic constant

## Test Cases
```python
# n=3: Magic constant = 15
# n=4: Magic constant = 34
# n=5: Magic constant = 65
```

## Implementation Notes
- Use AllDifferent constraint for uniqueness
- Consider symmetry breaking to reduce search space
- For odd n, there are known construction methods, but use constraint solving