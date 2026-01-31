# CPMPY project prompt

You are solving constraint programming problems using CPMpy.

## Core Rules

1. Use CPMpy's constraint modeling - never write search algorithms
2. Output ONLY valid JSON using `json.dumps()` - no other text
3. Always `import json` if outputting JSON
4. Check the exact output format required
5. Test your solution manually to verify it satisfies the problem

## Basic Template
```python
from cpmpy import *
import json

# Variables
# Constraints  
# Solve
if model.solve():
    # Build result dict as specified
    result = {...}
    # Verify solution satisfies problem requirements
    print(json.dumps(result))
else:
    print(json.dumps({"error": "No solution"}))
```

## Essential Constraints
- `AllDifferent(vars)` - all different values
- `sum(vars) == total` - sum constraint
- `Circuit(x)` - variables x form a Hamiltonian circuit (for routing/tour problems)
- `InDomain(var, [values])` - restrict variable to a set of values (import from cpmpy)
- Logical: `&`, `|`, `~` on constraints; `(cond).implies(other)` on constraints only
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=` between variables and expressions
- Element: `vars[idx]` where idx is a decision variable (direct indexing works)

## CPMpy Pitfalls - Avoid These
- Do NOT use `.is_in()`, `.in_domain()`, or other methods that don't exist — use `InDomain(var, list)` instead
- Do NOT use `~var` on integer variables — `~` only works on boolean constraints
- Do NOT call `.implies()` on integer variables — only on boolean expressions/constraints
- If an operator/method fails, fall back to explicit OR/AND over individual equality constraints
- When in doubt, use simple comparisons and loops instead of advanced abstractions

## Optimization
- Use `model.minimize(objective)` or `model.maximize(objective)`
- CPMpy automatically finds the OPTIMAL solution, not just first valid
- The solver continues searching until it proves optimality
- Always verify the objective value matches your expectation
- Example:
  ```python
  profit = sum(price[i] * x[i] for i in range(n))
  model.maximize(profit)
  ```

That's it. Read the problem carefully, model it declaratively, and let CPMpy find the optimal solution.