# CPbench Constraint Programming Task

You are solving a constraint programming problem described in natural language in PROBLEM.md.

## Section 1: The Mission - Core Rules & Workflow

### 1.1 Core Requirements & Output Format

1. **Primary Goal**: Produce a solution that passes your own programmatic verification.
   - **For optimization problems** (e.g., minimize cost, maximize profit, shortest path), you MUST use `model.minimize()` or `model.maximize()`. Using `model.solve()` is incorrect as it only finds the *first feasible solution*, which is likely not the *optimal* one.
   - **For satisfaction problems** (any valid solution is acceptable), use `model.solve()`.
2. **Tool Requirement**: You MUST use the CPMpy library for modeling and solving
3. **Execution Time**: Your script must complete within 10 seconds
4. **Output Format**:
   - Generate ONLY executable Python code (no brute-force or pure Python solutions)
   - Print the final solution as a single JSON object to stdout
   - **CRITICAL**: If PROBLEM.md contains "Output format (JSON):", you MUST follow that exact JSON structure with the specified keys (unless the problem is unsatisfiable)
   - Use the EXACT variable names specified in the problem's requirements or JSON template
   - Use 1-based indexing for all numerical positions, permutations, or assignments unless explicitly stated otherwise (Note: CPMpy and Python use 0-based indexing internally - convert as needed)
   - For boolean outputs, use integers `0/1` for broader compatibility
   - DO NOT transform solved variables unless the required format differs from the model's representation

### 1.2 The Required Workflow

This four-step process is REQUIRED for every problem.

#### Step 1: Deconstruct & Pre-compute
- Read `PROBLEM.md` and list all constraints and objectives in comments
- Analyze input data for implicit properties (e.g., sums, differences, divisibility)
- Handle ambiguities: If a term is unclear (e.g., "needs X items" could mean `==` or `>=`), choose the simplest interpretation and proceed
- Pre-compute fixed properties for use with Table constraints

Example pre-computation:
```python
# Validate numerical relationships in the data
ages = [10, 13, 15, 17, 20]
# Find all pairs with difference of 3
pairs_with_diff_3 = [(i,j) for i in range(len(ages)) 
                      for j in range(len(ages)) 
                      if ages[j] - ages[i] == 3]
print(f"Pairs with difference 3: {pairs_with_diff_3}")

# Calculate derived values
total_items = 100
num_groups = 5
items_per_group = total_items // num_groups
print(f"Each group gets {items_per_group} items")
```

#### Step 2: Model with CPMpy
1. **Choose your variables (The "View")**: Decide on the best representation
   - `intvar` for positions, counts, or selections
   - `boolvar` matrix for assignments or relationships
   
2. **Add Constraints Incrementally**: Start with core logic, use global constraints first
   
3. **Add Performance Constraints**: After the core model is defined, add symmetry breaking and redundant constraints
   <!-- Symmetry breaking improves solver performance -->
   - For interchangeable variables: `model += x[0] <= x[1]`
   - For circular arrangements: fix one position `model += positions[0] == 0`
   - For sequences: prevent reversal `model += seq[0] < seq[-1]`

#### Step 3: Solve & Verify (MANDATORY)
1. For optimization problems (minimize/maximize):
   - First call `model.minimize(objective)` or `model.maximize(objective)` to set the objective
   - Then call `model.solve()` to find the optimal solution
   - Note: minimize/maximize only set the objective, they don't solve the model
2. For satisfaction problems (just find any valid solution):
   - Use `model.solve()` directly
3. If `model.solve()` returns True, extract the `.value()` from your variables
4. **Write new, independent Python code to verify the solution**. This must check:
   - **Structural Correctness**: Verify that the output has the exact dimensions and shape required by the problem.
   - **Logical Correctness**: Verify that the solution values satisfy all original problem rules (feasibility).
   - **For optimization problems**: Re-calculate the objective function based on the returned solution and confirm it matches the objective value found by the solver. You are verifying *feasibility and correctness of the objective calculation*, not optimality itself. The solver handles proving optimality.
5. If verification fails for any reason, your model is wrong - return to Step 2.

Example verification:
```python
# After solving...
solution = {"assignments": assign.value().tolist()}

# Verification (independent of CPMpy)
def verify_solution(sol):
    # 1. Structural Verification
    # Check if the output matrix has the required dimensions
    assignments = np.array(sol["assignments"])
    if assignments.shape != (num_items, num_groups):
        return False, f"Structural failure: Shape is {assignments.shape}, expected {(num_items, num_groups)}"

    # 2. Logical Verification
    # Check constraint 1: each item assigned once
    if not np.all(np.sum(assignments, axis=1) == 1):
        return False, "Logical failure: An item was not assigned to exactly one group"
    
    return True, "All constraints satisfied"

valid, msg = verify_solution(solution)
assert valid, f"Verification failed: {msg}"
```

##### Post-Solve Quality Check
For optimization problems, after verifying correctness, briefly analyze the solution's quality. This helps ensure you haven't settled on a suboptimal solution.
- **Check for Slack**: Are there any resources (time, budget, capacity) that are significantly under-utilized? Unused capacity might indicate that a better objective value is possible.
- **Example**: If you minimized cost and the solution uses only 80% of the available budget, question if a different configuration could achieve an even lower cost. This is a good sanity check before finalizing.

#### Step 4: Finalize for Output
- Create the final, clean script in `solution.py`
- Ensure JSON output is correctly formatted with required variable names

### 1.3 Final Checklist

Before completing your solution, verify:

☐ 1. **Uses CPMpy constraints** - Solution uses `Model()` and constraint-based solving, NOT brute-force
☐ 2. **Model solves correctly** - `model.solve()` returns True
☐ 3. **Optimization applied** - If problem asks for optimal (min/max), used `model.minimize()` or `model.maximize()`, **confirming it's not just a feasible solution**.
☐ 4. **Solution verified (REQUIRED)** - Verification code confirms **both logical and structural (e.g., shape, dimensions)** correctness.
☐ 5. **Output format matches** - If PROBLEM.md has "Output format (JSON):", follow it EXACTLY
☐ 6. **Variable names exact** - Use names from JSON template or Requirements section
☐ 7. **JSON prints correctly** - Solution outputs valid JSON with correct keys and structure.
☐ 8. **Quality check performed** - For optimization problems, slack/resource usage was considered.
☐ 9. **No floating-point issues** - If data contains floats, they are scaled to integers for modeling.
☐ 10. **Array indexing correct** - Used `cp.cpm_array()` or `cp.Element()` for indexing with variables.
☐ 11. **File written** - Create `solution.py` with the complete working code.
☐ 12. **Final test** - Run `solution.py` to ensure it executes standalone.

## Section 2: The Toolkit - CPMpy Fundamentals

### 2.1 Basic Syntax

**Available packages**: The following packages are available for import:
- `cpmpy` - The constraint programming library
- `numpy` - For array operations
- `json` - For output formatting

```python
import cpmpy as cp
import numpy as np
import json

# Create model
model = cp.Model()

# Decision variables
x = cp.intvar(lb, ub, shape=dims, name="x")
b = cp.boolvar(shape=dims, name="b")

# Add constraints
model += [constraints]

# Solve
if model.solve():
    print(json.dumps({"solution": x.value().tolist()}))
```

### 2.2 Critical CPMpy Limitations & Handling

<!-- Based on CPMpy API documentation -->
#### Integers Only
CPMpy solvers work only with integers. Scale floating-point data before modeling.

```python
# Example: Scale float distances for TSP
distances_float = [[0, 2.5, 3.7], [2.5, 0, 1.2]]
SCALE = 100  # Choose based on precision needed
distances = [[int(d * SCALE) for d in row] for row in distances_float]

# Model with integers, scale back after solving if needed
total = cp.intvar(0, 100000)
model.minimize(total)
# After solving: actual_value = total.value() / SCALE
```

#### Array Indexing with Variables
Cannot index Python lists with decision variables. Use `cp.cpm_array()` wrapper or `cp.Element()`.

<!-- From CPMpy docs: Cannot index Python lists with variables directly -->
```python
# For CPMpy arrays: works directly
cparray[idx_var] == value

# For Python lists/numpy: need wrapper
cp.cpm_array(pylist)[idx_var] == value

# Or use Element explicitly
cp.Element(pylist, idx_var) == value
```

#### Operator Precedence
Always use parentheses with `&` and `|`: write `(x == 1) & (y == 0)` not `x == 1 & y == 0`

### 2.3 Global Constraints Catalog

Always prefer these over manual pairwise constraints:

#### Core Constraints (Very Common)
- `AllDifferent(x)` - All variables take different values
- `AllEqual(x)` - All variables take same value  
- `Count(x, val) == n` - Exactly n variables equal val
- `Table(vars, allowed_tuples)` - Variables must match allowed tuples
- `Element(arr, idx)` - Variable indexing: returns arr[idx] where idx is a variable

#### Sequencing Constraints
<!-- The following Circuit definition is verbatim from CPMpy API documentation -->
- `Circuit(x)` - "The sequence of variables form a circuit, where x[i] = j means that j is the successor of i."
- `Increasing(x)` - Variables in increasing order
- `Decreasing(x)` - Variables in decreasing order
- `IncreasingStrict(x)` - Strictly increasing

#### Assignment Constraints
- `Inverse(f, g)` - Channeling constraint: if f[i]=j then g[j]=i
- `AllDifferentExcept0(x)` - All non-zero values different

#### Scheduling Constraints
- `Cumulative(start, dur, end, demand, capacity)` - Resource scheduling
- `NoOverlap(start, dur, end)` - Tasks don't overlap
- `Precedence(x, vals)` - Enforces precedence order

#### Cardinality Constraints
- `GlobalCardinalityCount(x, vals, counts)` - Count occurrences
- `NValue(x) == n` - Exactly n distinct values
- `Among(x, vals) == n` - Count how many variables in x take values from vals

#### Ordering Constraints
- `LexLess(x, y)` - Lexicographic ordering x < y
- `LexLessEq(x, y)` - Lexicographic ordering x <= y

## Section 3: The Playbook - Common Problem Patterns

### 3.1 Sequencing & Permutation Problems

#### Pattern: Traveling Salesperson / Circuit
**Indicators:**
- "visit every location", "round trip", "traveling salesman", "tour", "collect items while traveling"
- "shortest tour", "minimize travel distance"
- Output asks for "next location/node/house after each current one"

**Implementation:**
```python
# For TSP/Circuit problems using successor representation
# x[i] = j means j is visited after i
successor = cp.intvar(0, n-1, shape=n, name="successor")
model += cp.Circuit(successor)

# If must start at node 0 and end at node 1:
model += successor[1] == 0  # Close circuit from destination back to start

# Calculate path costs/rewards using cpm_array for indexing
costs = cp.cpm_array(cost_matrix)
total_cost = cp.sum(costs[i, successor[i]] for i in range(n))
model.minimize(total_cost)
```

<!-- This example is adapted from CPMpy documentation -->
**Complete Example: 4-City TSP**
```python
import cpmpy as cp
import json

# Distance matrix between 4 cities
n = 4
distance_matrix = [
    [0, 20, 42, 35],
    [20, 0, 30, 34],
    [42, 30, 0, 12],
    [35, 34, 12, 0]
]

# Decision variables: successor[i] = j means visit city j after city i
successor = cp.intvar(0, n-1, shape=n, name="successor")

model = cp.Model()
model += cp.Circuit(successor)

# Calculate total distance
distances = cp.cpm_array(distance_matrix)
total_distance = cp.sum(distances[i, successor[i]] for i in range(n))
model.minimize(total_distance)

if model.solve():
    # Reconstruct the tour
    tour = []
    current = 0
    for _ in range(n):
        tour.append(current)
        current = successor.value()[current]
    
    solution = {
        "tour": tour,
        "successor": successor.value().tolist(),
        "total_distance": total_distance.value()
    }
    print(json.dumps(solution))
```

**TSP with Budget/Resource Constraint:**
<!-- Common TSP variations beyond basic Circuit -->
```python
# Must visit all nodes but stay within resource limit
successor = cp.intvar(0, n-1, shape=n)
model += cp.Circuit(successor)

# Add budget constraint (fuel, time, cost)
costs = cp.cpm_array(cost_matrix)  # MUST use cpm_array for indexing
total_cost = cp.sum([costs[i, successor[i]] for i in range(n)])
model += total_cost <= budget

# Still minimize primary objective
distances = cp.cpm_array(distance_matrix)
model.minimize(cp.sum([distances[i, successor[i]] for i in range(n)]))
```

**Note on Selective TSP/Orienteering:**
If the problem allows visiting only a subset of nodes (maximize reward within budget), the simple Circuit constraint is insufficient. This requires more complex modeling with node selection variables and subtour elimination.

#### Pattern: General Sequencing (N-Queens, Ordering)
**Indicators:**
- "arrange items in a line", "ordering tasks"
- "no two items can conflict", "place queens on board"

```python
# Example: N-Queens Problem
n = 8
queens = cp.intvar(1, n, shape=n, name="queens")  # Column position for each row

model = cp.Model()
model += cp.AllDifferent(queens)  # Different columns
model += cp.AllDifferent([queens[i] + i for i in range(n)])  # Different diagonals
model += cp.AllDifferent([queens[i] - i for i in range(n)])  # Different anti-diagonals

model.solve()
```

### 3.2 Assignment & Partitioning Problems

#### Pattern: Minimum Cost Assignment
**Indicators:**
- "assign workers to tasks", "match items to bins"
- "minimize total cost", "maximize efficiency"

```python
# Boolean assignment matrix
# assign[i,j] = 1 if item i assigned to bin j
assign = cp.boolvar(shape=(n_items, n_bins), name="assign")

# Each item assigned to exactly one bin
for i in range(n_items):
    model += cp.sum(assign[i,:]) == 1

# Each bin capacity respected
for j in range(n_bins):
    model += cp.sum(assign[:,j] * item_sizes) <= bin_capacity[j]

# Minimize cost
cost_matrix = cp.cpm_array(costs)
total_cost = cp.sum(assign * cost_matrix)
model.minimize(total_cost)
```

#### Pattern: Facility Location
**Indicators:**
- "open/close decisions with fixed costs"
- "assign items to facilities with variable costs"
- Keywords: "warehouse", "facility", "depot", "service center"

**Watch out for:** Local optima when few facilities are opened. The optimal solution might open MORE facilities (higher fixed cost) to achieve LOWER variable costs.

#### Pattern: Channeling Constraints (Multiple Views)
<!-- Pattern for complex assignment problems -->
**Indicators:**
- Problems involving bidirectional relationships
- Need to express constraints from multiple perspectives

```python
# Example: Assign people to houses (both directions needed)
person_to_house = cp.intvar(0, n-1, shape=n)  # person i in house person_to_house[i]
house_to_person = cp.intvar(0, n-1, shape=n)  # house j has person house_to_person[j]

# Channel between views using Inverse
model += cp.Inverse(person_to_house, house_to_person)

# Now use either view for constraints:
model += person_to_house[JOHN] != person_to_house[MARY]  # Different houses
model += house_to_person[BLUE] == JOHN  # John in blue house
```

### 3.3 Scheduling & Resource Management

#### Pattern: Sliding Window Constraints
<!-- Common pattern for scheduling and rostering -->
**Indicators:**
- "no more than X in any Y consecutive days"
- "rest period after work", "minimum gap between activities"

```python
# Pattern: "No more than X in any Y consecutive days"
work = cp.boolvar(shape=n_days)
max_work = 2
window_size = 4

for i in range(n_days - window_size + 1):
    model += cp.sum(work[i:i+window_size]) <= max_work

# Pattern: "Rest period after work"
rest_days = 2
for i in range(n_days - rest_days):
    # If work[i], then no work for next rest_days
    for j in range(1, rest_days + 1):
        model += work[i].implies(~work[i+j])
```

#### Pattern: Cumulative Resources
**Indicators:**
- "resource capacity", "parallel tasks", "limited resources"
- "tasks with duration and resource demand"

```python
# Tasks with start times, durations, and resource demands
starts = cp.intvar(0, horizon, shape=n_tasks, name="start")
durations = [task_durations]  # Given
ends = starts + durations
demands = [task_demands]  # Resource required by each task

# Resource capacity constraint
model += cp.Cumulative(starts, durations, ends, demands, capacity)
```

### 3.4 Graph/Network Problems

#### Pattern: Graph Coloring
**Indicators:**
- "color nodes such that adjacent nodes differ"
- "minimize chromatic number"

```python
# Graph represented as edges
edges = [(0,1), (1,2), (2,3)]
n_nodes = 4

colors = cp.intvar(0, n_nodes-1, shape=n_nodes, name="colors")
model = cp.Model()

# Adjacent nodes must have different colors
for i, j in edges:
    model += colors[i] != colors[j]

# Minimize number of colors used
model.minimize(cp.max(colors))
```

#### Pattern: Set Selection/Coverage
**Indicators:**
- "select minimum sets to cover all elements"
- "choose subsets that satisfy coverage requirements"

```python
# Binary variables for selecting sets
select = cp.boolvar(shape=n_sets, name="select")

# Coverage: each element must be covered by at least one selected set
for element in range(n_elements):
    covering_sets = [s for s in range(n_sets) if element in sets[s]]
    model += cp.sum([select[s] for s in covering_sets]) >= 1

# Minimize number of sets selected
model.minimize(cp.sum(select))
```

### 3.5 Optimization Objectives

#### Pattern: Resource Minimization (Non-Direct Variables)
<!-- Pattern for minimizing quantities not directly modeled -->
**Indicators:**
- "minimize number of colors/bins/groups used"
- "minimize maximum value"

```python
# Example: Minimize number of colors in graph coloring
colors = cp.intvar(0, max_colors-1, shape=n_nodes)
model += [adjacency constraints]

# METHOD 1: Direct use of cp.max() - CPMpy handles auxiliary variables
model.minimize(cp.max(colors))  # Minimizes highest color index used

# METHOD 2: Explicit auxiliary variable (if needed for complex cases)
max_color = cp.intvar(0, max_colors-1)
model += [colors[i] <= max_color for i in range(n_nodes)]
model.minimize(max_color)
```

#### Pattern: Multi-Objective
When multiple objectives exist, either:
1. Combine with weights: `model.minimize(w1*obj1 + w2*obj2)`
2. Optimize hierarchically: solve for obj1, fix it, then optimize obj2

## Section 4: Performance & Advanced Techniques

### 4.1 Performance & Efficiency

#### Variable Ordering
```python
# Fix first variable to break symmetry
model += x[0] == min_value

# Order interchangeable variables
model += x[0] <= x[1]
```

#### Redundant Constraints
Add logically redundant but computationally helpful constraints:
```python
# If we know the sum must equal a value
model += cp.sum(x) == total  # This might speed up search
```

#### Bounds Tightening
```python
# Instead of intvar(0, 1000), use tighter bounds
max_possible = min(capacity, total_items)
x = cp.intvar(0, max_possible)
```

### 4.2 Advanced Modeling

#### Auxiliary Variables
For complex expressions that appear multiple times or need to be constrained:
```python
# Instead of repeating complex expressions
# Create auxiliary variable for reuse
aux = cp.intvar(0, 100, name="aux")
model += aux == cp.sum(x[i] * weights[i] for i in range(n))
model += aux <= capacity
model.minimize(aux)
```

#### Channeling Between Representations
When you need both boolean matrix and integer array views:
```python
# Boolean matrix view: assign[i,j] = 1 if item i in bin j
assign = cp.boolvar(shape=(n_items, n_bins), name="assign")

# Integer array view: bin[i] = which bin contains item i
bin_of_item = cp.intvar(0, n_bins-1, shape=n_items, name="bin")

# Channel between the two views
for i in range(n_items):
    for j in range(n_bins):
        model += (bin_of_item[i] == j) == assign[i,j]
```

#### Pairwise Interactions (Efficient Pattern)
```python
from itertools import combinations

# For all pairs of items
for i, j in combinations(range(n), 2):
    model += constraint_between(x[i], x[j])
```

#### Solution Hints (Warm Start)
If you have a heuristic solution:
```python
# Assuming a heuristic solution for the variables
model.solve(assumptions=[x[0] == 5, x[1] == 3])
```

#### Finding Multiple Solutions
```python
model.solveAll()
for sol in model.solutions:
    print(sol)
```

## Section 5: Debugging & Verification

### 5.1 When model.solve() Returns False

Your model is unsatisfiable. Common causes:
1. **Over-constrained**: Constraints are too restrictive
2. **Bounds too tight**: Variable domains don't allow valid solutions
3. **Logic errors**: Incorrect constraint formulation

Debug by:
- Commenting out constraints one by one
- Relaxing bounds
- Printing the model to check for unexpected constraints
- Checking for index errors creating invalid constraints

### 5.2 Common CPMpy-Specific Errors

#### ImportError on `from cpmpy import *`
- Means CPMpy isn't available or environment is misconfigured
- Always use `import cpmpy as cp` instead

#### model.minimize() returns None
- This is normal! minimize() only sets the objective
- You must call model.solve() after minimize/maximize

#### TypeError with operators
- Remember: `&` not `and`, `|` not `or`, `~` not `not`
- Use parentheses: `(x == 1) & (y == 2)`

#### Mixing Python Logic with CPMpy
```python
# WRONG - Python evaluates immediately
if x > y:  # x and y are CPMpy variables
    model += z == 1

# CORRECT - Use CPMpy's conditional constraints
model += (x > y).implies(z == 1)
```

#### Variable Bounds Mismatch
```python
# If you get unexpected unsatisfiable models
# Check variable bounds match problem requirements
x = cp.intvar(1, 10)  # Is 0 needed? Is upper bound sufficient?
```

### 5.3 Interpreting Ambiguous Requirements

When problem descriptions are unclear:
- Choose the simplest valid interpretation
- If "at least" vs "exactly" is ambiguous, try "exactly" first
- Document assumptions in comments
- Verify your interpretation makes the problem solvable

## Performance Tips

- Use global constraints (AllDifferent, Circuit) over manual decomposition
- Add symmetry breaking early in the model
- Prefer linear objectives when possible
- For large problems, consider adding redundant constraints
- Use tight variable bounds based on problem analysis

## Solution Template

```python
import cpmpy as cp
import numpy as np
import json

# Step 1: Deconstruct & Pre-compute
# [Analyze problem, identify constraints]

# Step 2: Model with CPMpy
n = # problem size
model = cp.Model()

# Decision variables
x = cp.intvar(lower, upper, shape=shape, name="x")

# Constraints
model += [constraints]

# Performance improvements
# [Add symmetry breaking and redundant constraints]

# Step 3: Solve and verify
# For optimization:
# model.minimize(objective) or model.maximize(objective)

if model.solve():
    # Extract solution
    solution = {
        "key": x.value().tolist() if hasattr(x.value(), 'tolist') else x.value()
    }
    
    # Verification
    def verify_solution(sol):
        # Check all constraints
        return True
    
    assert verify_solution(solution), "Solution verification failed!"
    
    # Step 4: Output
    print(json.dumps(solution))
else:
    print(json.dumps({"error": "No solution found"}))
```

## Final Reminders

- Read the problem carefully - every constraint matters
- Always verify your solution independently
- Check output format requirements multiple times
- Use meaningful variable names for debugging
- Comment your constraint logic
- Test with small instances first if possible