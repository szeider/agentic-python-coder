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
- `InDomain(var, [values])` - restrict variable to a set of values. **Must be explicitly imported**: `from cpmpy import InDomain`
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

## Output Format Rules
- Follow the output JSON format specification EXACTLY — do not invent alternative encodings
- If a field is described as nested arrays, output nested arrays (e.g., `[[1,2],[3,4]]`), never compress to single integers
- Reconcile the task text with the output specification before modeling
- If they conflict, or the task mentions variants or extensions of the problem, solve the problem that the output specification describes and state the assumption in a code comment or your final message
- Derive every output array's dimensions from parameters stated in the problem and from the axis names in the format spec: `result[a][b]` means outer axis `a` and inner axis `b` — never swap axes or substitute a different quantity
- Check array dimensions and value ranges match the spec before saving

## Verification Requirement (MANDATORY)

CPMpy models can easily contain subtle logic bugs. Before saving, you MUST:

1. **Solve and extract** the solution values
2. **Write a `verify()` function** that checks every constraint from the problem statement using plain Python loops and asserts — independent of your CPMpy model:
   ```python
   def verify(result, sizes, capacities):
       # sizes, capacities: the problem data, NOT variables of your model
       bins = result["assignment"]  # bins[i] = bin of item i (output spec)
       assert len(bins) == len(sizes), "every item assigned exactly once"
       assert all(0 <= b < len(capacities) for b in bins), "bin out of range"
       # Check each constraint with plain Python
       for b, cap in enumerate(capacities):
           load = sum(s for s, a in zip(sizes, bins) if a == b)
           assert load <= cap, f"bin {b} over capacity"
       # ... check ALL constraints from the problem statement
       # No print here: a failed assert raises, stdout is for the JSON
   ```

   The verifier must be derived from the problem text alone: re-read the problem
   statement and re-derive every expected dimension, entry encoding, and constraint
   from its own parameters. Never assert against quantities or interpretations that
   your model introduced — `assert len(x) == my_total` proves nothing if `my_total`
   encodes a misreading. If your model and your verifier share an assumption, a
   wrong assumption passes silently.
3. **Execute the verification** via python_exec and confirm it passes (diagnostic prints are fine while developing; the saved code prints only the JSON)
4. **For optimization**: verify optimality by re-solving with a stricter bound:
   ```python
   model2 = Model(model.constraints)
   model2 += objective < best_value  # or > for maximize
   assert not model2.solve(), "Solution is not optimal"
   ```

Do NOT call save_code until verification passes. If it fails, fix the model and re-verify.

That's it. Read the problem carefully, model it declaratively, verify independently, and let CPMpy find the optimal solution.