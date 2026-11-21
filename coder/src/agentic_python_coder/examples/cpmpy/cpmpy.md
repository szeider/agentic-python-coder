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
- `InDomain(var, [values])` - restrict variable to a set of values (included in `from cpmpy import *`)
- Logical: `&`, `|`, `~` on constraints; `(cond).implies(other)` on constraints only
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=` between variables and expressions
- Element: `vars[idx]` where idx is a decision variable (direct indexing works on an NDVarArray: `intvar(..., shape=n)` with n > 1, `shape=(n,)`, or `cpm_array(list)`; not on a Python list, and `shape=1` gives a scalar)

## CPMpy Pitfalls - Avoid These
- Do NOT use `.is_in()`, `.in_domain()`, or other methods that don't exist — use `InDomain(var, list)` instead
- Do NOT use `~var` on integer variables — `~` only works on boolean constraints
- Do NOT call `.implies()` on integer variables — only on boolean expressions/constraints
- If an operator/method fails, fall back to explicit OR/AND over individual equality constraints
- When in doubt, use simple comparisons and loops instead of advanced abstractions
- Reachability where an edge needs an item picked up earlier on the same walk (keys, tools, switches): a fixpoint over reached nodes that pools every collected item over-approximates once edges are one-way, since the agent may not get back. Model walks instead (`boolvar` arrays `at[n,t]`, `holds[i,t]`) with |nodes| * 2^k - 1 steps for k items and a stay-in-place step, so a walk may stop early. For "every node reachable", give each target its own witness walk, all over the same layout variables in one model: not one walk through all targets, and not one solver call per target with a generated layout left free.

## Optimization
- Use `model.minimize(objective)` or `model.maximize(objective)`
- Without a time limit the solver searches until it proves optimality; with a limit (`model.solve(time_limit=...)`) the result may be merely feasible, see Verification step 4
- Optimization can be slow with loose variable bounds: keep domains as tight as the problem allows. A run that hits a time limit does NOT mean the model is wrong
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
- For UNSAT, output the format's UNSAT form (or `{"error": "No solution"}` if none is specified)

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
   wrong assumption passes silently. Check the solution against the statement's
   own definitions by direct computation in plain Python (simulate the process,
   recount, recompute), not by repeating the derivation the model used; a
   verifier that mirrors the encoding passes whatever the encoding gets wrong.
3. **Execute the verification** via python_exec and confirm it passes (diagnostic prints are fine while developing; the saved code prints only the JSON).
   The default solver, OR-Tools CP-SAT, searches with parallel workers, so two
   runs may return different solutions: run the solve and the verification more
   than once, or solve with `model.solve("ortools", num_workers=1)` (solver
   parameters need the solver name) for a reproducible run, unless a time limit
   stops it.
4. **For optimization**: the verifier recomputes the objective value from the
   data (pass the reported value to it together with the data). Optimality is
   decided by the solver's status, not by `model.solve()`'s return value:
   ```python
   from cpmpy.solvers.solver_interface import ExitStatus
   found = model.solve(time_limit=60)        # time_limit optional
   status = model.status().exitstatus
   proven_optimal = status == ExitStatus.OPTIMAL
   proven_unsat = status == ExitStatus.UNSATISFIABLE
   ```
   `model.solve()` returns True also when a time limit stopped it with a merely
   feasible solution (`ExitStatus.FEASIBLE`): optimality is then not proven.
   `model.solve()` returning False is no proof of infeasibility: under a time
   limit it also returns False when the limit stopped it before any solution
   (`ExitStatus.UNKNOWN`); only `ExitStatus.UNSATISFIABLE` proves that no
   solution exists. Without `time_limit` the solve returns only when finished.
   A program that stops the solver before it finishes (time limit, solution
   limit) reports a result as optimal, or the problem as unsatisfiable, only if
   the status proves it. Otherwise the output says so (error JSON with a reason,
   or the solution together with the status field if the output format has
   one), and the final answer states that optimality or unsatisfiability was
   not proven.
5. **Example outputs**: an example output in the problem statement fixes the output format (keys, nesting, types). Its values count as a solution only if the problem says so. If the problem presents the example as a valid or expected solution, run it through your verifier: a failure means the specification, the example, the model and the verifier must be reconciled; if the specification and the example really conflict, report the conflict. If the problem marks it as a dummy or says nothing about its validity, do not copy its values and do not test against them.

Do NOT call save_code until verification passes. If it fails, fix the model and re-verify.

### If the model reports no solution

Read the exit status first (step 4): `ExitStatus.UNKNOWN` (a time limit hit
before any solution) means unresolved, not infeasible. The steps below apply to
`ExitStatus.UNSATISFIABLE`.

`model.solve()` returning False is far more often a buggy, over-constrained
model than a genuinely infeasible problem. Before reporting "No solution":

1. Re-read the problem and confirm EVERY constraint you added is actually
   required by the problem statement (or is a valid symmetry-breaking
   constraint that cannot exclude all optimal solutions).
2. Suspect your own encoding first — comment out constraints one at a time
   to find which one makes it infeasible, then check that constraint against
   the problem text.
3. Only once every remaining constraint is grounded in the problem, and the
   status is `ExitStatus.UNSATISFIABLE` (see step 4), is UNSAT a valid answer.
   Then trust the solver — do not try to prove *why* it is infeasible; report it.

That's it. Read the problem carefully, model it declaratively, verify independently, and let CPMpy find the optimal solution.