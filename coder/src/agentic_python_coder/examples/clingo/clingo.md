# Answer Set Programming (ASP) Task - v10

## Section 1: Mission Briefing & Core Requirements

### Primary Goal
Produce a solution using Answer Set Programming (ASP) that correctly models and solves the problem using the clingo Python API.

### Non-Negotiable Requirements
1. **Tool**: You MUST use the clingo Python API for modeling and solving
2. **Time Limits and Objectives**: Follow any time limit the task states
   - **Optimization vs Bounds**: If the problem asks for an optimum, keep the objective (`#minimize`/`#maximize`). If the task states an optimal value or bound as a fact, you may add it as a constraint to speed up search, in addition to the objective, not instead of it. Report the objective value reached.
   - **Example**: Keep `#minimize { Cost : total_cost(Cost) }.` and, for a stated bound of 50, add `:- total_cost(Cost), Cost > 50.`
3. **Output Format**: Print the final solution as a single JSON object to stdout
4. **Task Planning**: Structure your approach with clear steps:
   - Mentally break down the problem into 5-8 logical tasks
   - Follow the structured workflow defined below
   - Use code comments to track your progress through tasks
5. **Error Documentation**: Report environment/specification issues in a code comment or your final message

### Output Specifications
- Generate ONLY executable Python code using clingo
- Use clear, meaningful predicate names (e.g., `assigned(task1, worker2)` not `p(1,2)`)
- Extract solutions from answer sets and format as JSON
- Handle UNSAT cases gracefully with error JSON: `{"error": "No solution exists", "reason": "..."}`

### Final Checklist
Before completing your solution, verify:
☐ 1. **Uses clingo API** - Solution uses `clingo.Control()` and ASP rules
☐ 2. **Model solves correctly** - At least one answer set is found (or UNSAT handled)
☐ 3. **Optimization applied** - If problem asks for optimal, use #minimize/#maximize
☐ 4. **Solution extracted** - Answer set atoms properly extracted and formatted
☐ 4b. **No Model escapes on_model** - All solution data extracted to plain Python objects inside the callback (touching a Model after solve() returns segfaults)
☐ 5. **Output format correct** - JSON output with appropriate structure
☐ 6. **Predicates meaningful** - Clear names that reflect the problem domain
☐ 7. **Constraints verified independently** - All problem constraints are encoded AND re-checked by a plain-Python verify() whose expectations are re-derived from the problem text, not from your encoding's own interpretation
☐ 8. **Code saved** - Complete working code saved once with the save_code tool, after verification

## Section 2: Critical Rules of Engagement

### MANDATORY RULE: Core ASP Syntax

**FUNDAMENTAL RULE**: You must follow these basic syntax rules. Errors here are the most common cause of failures.

#### A. Constants vs. Variables
This is the single most important distinction in ASP syntax.

* **Constants (Symbols)**: Must start with a **lowercase letter**, be a **number**, or be enclosed in **double quotes `""`**.
  * `item(apple).` (lowercase)
  * `cost(100).` (number)
  * `amino_acid(1, "H").` (quoted string - **use this for input data that is uppercase**)

* **Variables**: Must start with an **uppercase letter** or an **underscore `_`**.
  * `has_color(Item, Color) :- ...`
  * `cost(X, C) :- ...`

**Common Mistake and Correction:**

| Incorrect (produces "unsafe variable" error) | Correct |
|:----------------------------------------------|:--------|
| `amino_acid(1, H).` | `amino_acid(1, "H").` **(Best Practice)** or `amino_acid(1, h).` |
| `type(engine, V8).` | `type(engine, "V8").` or `type(engine, v8).` |
| `player(P1).` | `player(p1).` or `player("P1").` |

#### B. The Closed World Principle: Never Hallucinate Data

**FUNDAMENTAL RULE**: Your ASP program operates under a **Closed World Assumption**. This means anything not explicitly stated as a fact or derivable from a rule is considered **false**. You MUST NOT invent or assume data that isn't provided.

All data must come from two places only:
1.  **Facts generated from the problem description.**
2.  **New facts derived by your rules from existing facts.**

**Common Mistake and Correction:**

| Incorrect (Hallucinates data) | Correct |
|:----------------------------------------------|:--------|
| **Problem:** "The available parts are a `cpu` and a `gpu`." <br/><br/> `part(cpu; gpu; ram).` <br/><br/> **Error**: The program invented `part(ram)`, which was not in the problem description. | **Problem:** "The available parts are a `cpu` and a `gpu`." <br/><br/> `part(cpu). part(gpu).` <br/><br/> **Explanation**: Only facts directly corresponding to the input are created. |
| **Problem:** "Schedule tasks for workers `w1`, `w2`." <br/><br/> `worker(W) :- assigned(_, W).` <br/><br/> **Error**: This only defines workers *if* they get a task. If `w2` is a valid worker but gets no tasks, `worker(w2)` will not be true. | **Problem:** "Schedule tasks for workers `w1`, `w2`." <br/><br/> `worker(w1). worker(w2).` <br/><br/> **Explanation**: The set of all possible workers is explicitly defined as facts from the problem input. |
| **Problem:** "Costs are: R1→C1: 10, R1→C2: 12" <br/><br/> `cost("R1","C1",10). cost("R1","C2",12). cost("R2","C2",12).` <br/><br/> **Error**: Invented cost for R2→C2 not in problem. | **Problem:** "Costs are: R1→C1: 10, R1→C2: 12" <br/><br/> `cost("R1","C1",10). cost("R1","C2",12).` <br/><br/> **Explanation**: Only the explicitly stated costs are created as facts. |

#### Hierarchy of Truth: Data Tables vs. Example Outputs

**CRITICAL RULE**: When a problem specification contains both data tables/lists AND example outputs, the **data tables, not the examples, supply the instance's values** unless the task declares an example normative, and the task's explicit constraints still apply to that data. Example outputs demonstrate the required **format** only - their **values** are illustrative.

**NEVER modify, invent, or transfer data to match an example output.** Your model must solve the problem defined by the data tables, even if the example's values appear inconsistent.

**Why This Matters:**
- Example outputs may contain typos or be slightly out of sync with primary data
- Example values are often from a different instance or simplified scenario
- Modifying data to match examples violates the Closed World Principle

**Common Mistake and Correction:**

| Incorrect (Modifies data to match example) | Correct (Uses only primary data) |
|:----------------------------------------------|:--------|
| **Data Table:** "Connection costs: A→B: 5, A→C: 10" <br/><br/> **Example Output:** Shows B connected to C <br/><br/> `cost("A","B",5). cost("A","C",10). cost("B","C",8).` <br/><br/> **Error**: Invented cost(B,C,8) to match example structure | **Data Table:** "Connection costs: A→B: 5, A→C: 10" <br/><br/> **Example Output:** Shows B connected to C <br/><br/> `cost("A","B",5). cost("A","C",10).` <br/><br/> **Explanation**: Use ONLY the provided costs. The solver finds the optimal solution using the true data. |
| **Data:** "Capacities: Server1: 100GB, Server2: 200GB" <br/><br/> **Example:** Shows Server3 in use <br/><br/> `capacity("Server1",100). capacity("Server2",200). capacity("Server3",150).` <br/><br/> **Error**: Added Server3 because example showed it | **Data:** "Capacities: Server1: 100GB, Server2: 200GB" <br/><br/> **Example:** Shows Server3 in use <br/><br/> `capacity("Server1",100). capacity("Server2",200).` <br/><br/> **Explanation**: Example is from a different instance. Use only the provided servers. |

**Priority Order:**
1. **Primary data tables/lists** (highest priority for values)
2. **Explicit problem constraints** (apply to the data; if the two conflict, report the conflict instead of changing either)
3. **Example output structure** (format guidance only)
4. **Example output values** (ignore if inconsistent)

#### C. Structure of Rules and Facts
* Every statement (fact or rule) **MUST** end with a period (`.`).
* In a rule body, a comma (`,`) means **AND**.
* Comments start with a percent sign (`%`).

```asp
% This is a FACT. It ends with a period.
city("paris").

% This is a RULE. Note the period at the end.
% "is_in_france(X) is true IF city(X) is true AND X is "paris"."
is_in_france(X) :- city(X), X == "paris".
```

### MANDATORY RULE: Variable Safety

**FUNDAMENTAL RULE**: Every variable appearing in a rule MUST be grounded by appearing in at least one positive, non-aggregate, non-arithmetic literal in the rule's body, or be assigned from bound variables (`K = #sum { ... }`, `Y = X+1`).

This concerns the rule's global variables. A variable local to a conditional literal or an aggregate element (`{ a(X) : b(X) }`, `#count { X : p(X) }`) is bound by the condition inside that element; such a local binding does not bind a global variable of the same name elsewhere in the rule (`h(X) :- #count { X : p(X) } > 0.` is unsafe).

**Why this matters**: ASP needs to know which values to check. Unsafe variables have no defined domain.

**Examples of UNSAFE vs SAFE rules**:
```asp
% UNSAFE - Variable S has no positive grounding
:- item(I), not on_shelf(I, S).
% Error: 'S' is unsafe - solver doesn't know which shelves to check

% SAFE - Variable S is grounded by shelf(S)
:- item(I), shelf(S), not on_shelf(I, S).
% Now solver checks all combinations of items and shelves

% UNSAFE - Variables X,Y only appear in negation
:- robot(R), not at(R,X,Y).
% Error: 'X' and 'Y' are unsafe

% SAFE - Variables X,Y grounded by location/2
:- robot(R), location(X,Y), not at(R,X,Y).
% Now solver knows to check all valid locations
```

#### Variable Safety with Negation as Failure (`not`)

A critical application of this rule is when using negation (`not`). Any variable used inside a `not` literal **must** be grounded by a positive literal elsewhere in the same rule body. The solver cannot find solutions by iterating through infinite possibilities of what is *not* true.

**Example: Finding unassigned tasks**
Imagine you have `task(1..10)` and `assigned(T, W)` facts for tasks that are already assigned. You want to write a rule to find unassigned tasks.

| Incorrect (produces "unsafe variable" error) | Correct |
|:----------------------------------------------|:--------|
| `unassigned(T) :- not assigned(T, W).` <br/><br/> **Error:** The variable `W` is unsafe. The solver doesn't know which set of workers (`W`) to check for non-assignment. | `unassigned(T) :- task(T), not assigned(T, _).` <br/><br/> **Explanation:** `task(T)` grounds the `T` variable. The underscore `_` in `not assigned(T, _)` checks for the existence of *any* assignment for that specific task `T`, correctly identifying tasks with no assignments. |

**Example: Circuit diagnosis - literal order does not matter**
Safety does not depend on the order of body literals: a variable used in negation is safe if it also occurs in some positive literal anywhere in the same body.

| Incorrect (unsafe variable error) | Correct |
|:----------------------------------------------|:--------|
| `wire_value(T, W, V) :- not faulty(G, _), correct_output(T, W, V).` <br/><br/> **Error:** `G` is unsafe - it occurs only in `not faulty(G, _)`. | `wire_value(T, W, V) :- not faulty(G, _), gate_output(G, W), correct_output(T, G, V).` <br/><br/> **Explanation:** `gate_output(G, W)` grounds `G`, whether it is written before or after the negated literal. Now `not faulty(G, _)` checks if *that specific gate* is healthy. |

#### Choice Rule Variable Safety

**CRITICAL RULE**: Variables in choice rules must be grounded either:
1. **In the choice domain** (after the `:` inside `{...}`), OR
2. **In the rule body** (after the `:-`)

Variables appearing in the choice head but nowhere else are UNSAFE.

**General Pattern:**
```asp
% UNSAFE - Variables in choice head but not grounded
{chosen(X, Var1, Var2)} :- domain(X).
% Error: 'Var1' and 'Var2' have no defined domain

% SAFE - Option 1: Ground in choice domain
{chosen(X, Var1, Var2) : property1(Var1), property2(Var2)} :- domain(X).

% SAFE - Option 2: Ground in rule body
{chosen(X, Var1, Var2)} :- domain(X), property1(Var1), property2(Var2).
```

**Example: Assignment**
```asp
% UNSAFE
{assign(Task, Worker, Priority)} :- task(Task).

% SAFE - Ground in choice domain
{assign(Task, Worker, Priority) : worker(Worker), priority(Priority)} :- task(Task).
```

**Example: Pairing**
```asp
% UNSAFE
{pair(Group, P1, P2)} :- group(Group).

% SAFE
{pair(Group, P1, P2) : member(P1), member(P2), P1 != P2} :- group(Group).
```

### MANDATORY RULE: Aggregate Placement

**Aggregates (#count, #sum, #min, #max) are used:**
- In the BODY of a rule (for conditions)
- In #minimize/#maximize statements
- As a whole rule head, in the form of choice and cardinality heads (`1 { a(X) : b(X) } 2 :- c.` or `#count { X : a(X) : b(X) } = 1 :- c.`)
- NEVER as an argument of a head atom, as in `total(#sum{...})`

**Why**: An atom's arguments are terms, and an aggregate is not a term; compute the value in the body and pass the variable.

```asp
% CORRECT - Aggregate in constraint body
:- #count { X : selected(X) } > 5.

% CORRECT - Aggregate in optimization
#minimize { Cost,X : selected(X), cost(X,Cost) }.

% INCORRECT - An aggregate cannot be an argument of a head atom
% total(#sum{C,X : cost(X,C)}) :- ...  % SYNTAX ERROR!

% CORRECT - Use auxiliary predicates instead
total(T) :- T = #sum{C,X : selected(X), cost(X,C)}.
```

### MANDATORY RULE: State Exclusivity (Fluents)

**FUNDAMENTAL PRINCIPLE**: When the task specifies a property that changes over time (a "fluent") as single-valued, such as the location of an object, you MUST enforce that it has at most one value at any given time.

**Critical for temporal problems**: An entity cannot be in two states simultaneously.

```asp
% INCORRECT - Allows item to be in two places
item_at(I,X,Y,T+1) :- item_at(I,X,Y,T), not pickup(_,I,T).
carrying(R,I,T+1) :- pickup(R,I,T).
% BUG: Item can be both at location AND carried!

% CORRECT - Enforce mutual exclusivity
% Item cannot be in two different places
:- item_at(I,X1,Y1,T), item_at(I,X2,Y2,T), (X1,Y1) != (X2,Y2).

% Item cannot be both on grid AND carried
:- item_at(I,X,Y,T), carrying(_,I,T).
```

### Required 5-Step Workflow

#### Step 0: Plan Your Approach (MANDATORY - DO THIS FIRST!)

**Structure your solution with these logical tasks:**
```python
# Task Plan:
# 1. Analyze problem and identify constraints
# 2. Design ASP predicates and model structure  
# 3. Implement facts and choice rules
# 4. Add constraints and optimization
# 5. Solve and extract solution
# 6. Format output as JSON
# 7. Test and verify solution
```

Use comments in your code to indicate which task you're working on:
```python
# Task 1: Analyze problem and identify constraints
# [Your analysis code here]

# Task 2: Design ASP predicates and model structure
# [Your design code here]
```

#### Step 1: Analyze & Model
- Identify objects/entities, relationships, constraints, optimization criteria
- Design appropriate predicates
- **Parse input data and generate ASP facts from problem description**
- **Identify fluents (changing properties) and enforce exclusivity**

#### Step 2: Implement with Clingo
- Create Control object
- Add ASP rules (facts, choice rules, constraints, optimization)
- Ground the program
- **Follow the Three-Step Action Pattern for temporal problems**

#### Step 3: Solve & Extract Solutions
- Configure solver parameters
- Extract atoms from answer sets
- Handle multiple solutions or optimization

#### Step 4: Format & Verify Output
- Convert to required JSON format
- Verify solution satisfies constraints
- Handle UNSAT cases gracefully
- **Proof status after an early stop**: a program that stops the solver before it finishes (time limit, cancel, solution or conflict limit) reads the solver's proof status and reports a result as optimal, or the problem as unsatisfiable, only if the solver proved it. Otherwise the output says so: the error JSON carries the reason (for example `{"error": "No solution found", "reason": "search stopped before UNSAT was proven"}`), or a solution is output together with the status field if the output format has one, and the final answer states that optimality or unsatisfiability was not proven. In clingo:
  - `result.exhausted` means the configured search ran to its end. UNSAT is proven when `result.unsatisfiable` is True (under the assumptions and bounds of that solve).
  - With the default optimization mode, the last model is proven optimal when the result is satisfiable and `exhausted` is True; under `--opt-mode=optN`, read `m.optimality_proven` on the model inside `on_model`.
  - A solve cancelled by `handle.cancel()` has `interrupted` True; a stop by a model limit (`Control(["1"])`, `--models=1`) has neither `exhausted` nor `interrupted` set, so "not interrupted" is no proof.
  - A time limit is an async solve; `ctl.solve()` without a limit returns only when finished:
    ```python
    with ctl.solve(async_=True, on_model=on_model) as handle:
        finished = handle.wait(t)   # t seconds
        if not finished:
            handle.cancel()
        result = handle.get()
    ```

### When to Report Issues

Report issues in a code comment or your final message ONLY for:
- Missing packages or imports
- Inconsistencies or ambiguities in problem description
- Conflicting constraints that make problem unsolvable
- Environment setup problems
- API compatibility issues

NOT for your own logic errors or debugging.

### 2.5 How to Express Constraints - The Eliminative Mindset

**CRITICAL**: ASP constraints work by ELIMINATION, not assertion. You forbid what's invalid, not state what's valid.

**Common Constraint Patterns:**

```asp
% To enforce X >= Y, forbid X < Y
% WRONG: :- capacity >= 32.  % This would forbid ALL solutions!
% CORRECT: Forbid capacity being less than 32
:- selected_ram(R), ram(R,_,Capacity,_,_), Capacity < 32.

% To enforce X > Y, forbid X <= Y
:- deadline(D), current_day(C), D <= C.  % Deadline must be after today

% To enforce X != "bad_value", forbid X = "bad_value"  
:- status(X, "invalid").  % No entity can have invalid status

% To enforce at least one selection, forbid having none
:- not selected(_).  % At least one must be selected

% To enforce mutual exclusion, forbid both being true
:- has_property(X, hot), has_property(X, cold).  % Can't be both
```

**Remember**: Think "what makes a solution invalid?" then write `:- invalid_condition.`

### 2.6 Hard vs Weak Constraints

**Use the right tool for the job:**

**Integrity Constraints (`:-`)**: Define what is IMPOSSIBLE
```asp
% These eliminate invalid answer sets entirely
:- overlapping_tasks(T1,T2).  % No overlaps allowed
:- budget_exceeded.            % Hard budget limit
```

**Weak Constraints (`:~`)**: Define what is UNDESIRABLE  
```asp
% These guide optimization without eliminating solutions
:~ delayed(Task). [1@2,Task]   % Prefer on-time, priority 2 (Task in the tuple: each delayed task counts)
:~ cost(C). [C@1]              % Minimize cost, priority 1
```

### 2.7 Multi-Objective Optimization

The order of `#minimize`/`#maximize` statements does not set priorities. Without `@` levels, all statements share one level and their weights are added into a single objective (identical tuples count once, so include an identifier such as `P` in each tuple). Use `@` levels for priorities; clingo optimizes the highest level first:

```asp
% Optimized in this order:
#maximize { S@3,P : chosen(P), ai_performance(P,S) }.   % First priority
#maximize { S@2,P : chosen(P), gaming_score(P,S) }.     % Second priority
#minimize { C@1,P : chosen(P), cost(P,C) }.             % Third priority
```

Weights within one level (for example `S*3` and `S*2`) express trade-offs; levels express strict priorities.

## Section 3: Clingo API & Implementation Guide

### Basic API Flow

```python
import clingo
import json

# Create control object
ctl = clingo.Control()

# Add ASP program
program = """
% Facts from input
% ... generated facts ...

% Choice rules
{ choice(X) } :- domain(X).

% Constraints
:- invalid_condition.

% Optimization
#minimize { Cost,X : selected(X), cost(X,Cost) }.
"""
ctl.add("base", [], program)

# Ground the program
ctl.ground([("base", [])])

# Solve and extract
solution = None
def on_model(m):
    global solution
    atoms = m.symbols(atoms=True)
    # Process atoms into solution (with an objective this runs once per
    # improving model; the last call holds the best model)
    
result = ctl.solve(on_model=on_model)

# Output
if result.satisfiable:
    print(json.dumps(solution))
else:
    print(json.dumps({"error": "No solution exists"}))
```

### CRITICAL: Finding One vs. All Solutions (Solver Configuration)

A frequent and critical error is misconfiguring the solver to search for all possible solutions when only one is required. This is a leading cause of timeouts on moderately complex problems. The number of models to find is controlled by the first argument to `clingo.Control()`; leave it out unless the task asks for all solutions.

> **Fundamental Rule:** Use `ctl = clingo.Control()`. Without an objective it stops after the first model; with `#minimize`/`#maximize` it reports a sequence of improving models and the LAST one is optimal when `result.exhausted` is true.

| Configuration                  | Without an objective                | With `#minimize`/`#maximize`                                                                 | Use                                                                                     |
| :----------------------------- | :---------------------------------- | :------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------- |
| `ctl = clingo.Control()`       | **Stops after the first model.**    | **Continues to an optimal model** (take the last model; `result.exhausted` = optimum proven; after an early stop see "Proof status" in Step 4 of the workflow). | **Your default for most tasks.**                                                        |
| `ctl = clingo.Control(["0"])`  | **Enumerates all models.**          | Same as `Control()`. For ALL optimal models use `["0", "--opt-mode=optN"]` and keep the models with `m.optimality_proven`. | **Only** when the task asks for every solution; otherwise it **leads to timeouts**.     |
| `ctl = clingo.Control(["1"])`  | Same as `Control()`.                | **Stops at the first model, which need not be optimal** (clingo warns "optimality of last model not guaranteed"). | **Never together with an objective.**                                                   |

### The Three-Step Action Modeling Pattern (CRITICAL for temporal problems)

For EVERY action in temporal/planning problems, you MUST model three aspects:

#### 1. Choice Rule (Generation)
Define when an action CAN possibly occur:
```asp
% Robot can try to pickup any item at any valid time
{ pickup(R,I,T) : item(I) } 1 :- robot(R), time(T), T < max_time.
```

#### 2. Precondition Constraints (Validation)
Define when an action is INVALID (prune invalid choices):
```asp
% Cannot pickup if robot and item at different locations
:- pickup(R,I,T), robot_at(R,RX,RY,T), item_at(I,IX,IY,T), (RX,RY) != (IX,IY).

% Cannot pickup if already carrying something
:- pickup(R,I,T), carrying(R,_,T).
```

#### 3. Effect Rules (State Change)
Define the NEW STATE resulting from a valid action:
```asp
% Pickup causes carrying at next timestep
carrying(R,I,T+1) :- pickup(R,I,T).

% Item no longer has location after pickup
% (Enforced by mutual exclusivity constraint)
```

### Passing Data to ASP

```python
def generate_facts(problem_data):
    facts = []
    for item in problem_data["items"]:
        facts.append(f'item("{item}").')
    return " ".join(facts)
```

### Extracting Solutions

```python
def extract_solution(model):
    solution = {}
    for atom in model.symbols(atoms=True):
        if atom.match("assigned", 2):
            task = str(atom.arguments[0])
            worker = str(atom.arguments[1])
            if worker not in solution:
                solution[worker] = []
            solution[worker].append(task)
    return solution
```

### CRITICAL: The Model Object Is Only Valid Inside on_model (Segfault Risk)

The `clingo.Model` object passed to your `on_model` callback is only valid DURING
that callback. After `ctl.solve()` returns, clingo frees the underlying model —
touching it later is a use-after-free that crashes the Python process with a
segmentation fault (exit code 139) and NO Python traceback.

Extract everything you need into plain Python objects (ints, strings, lists, dicts)
INSIDE the callback. Never store the Model object itself for later use.

```python
# WRONG - segfaults after solve() returns:
saved = None
def on_model(m):
    global saved
    saved = m                        # Model outlives the callback
ctl.solve(on_model=on_model)
atoms = saved.symbols(atoms=True)    # use-after-free -> SIGSEGV, no traceback

# CORRECT - extract inside the callback:
result = []
def on_model(m):
    # replace, do not append: with an objective, every improving model calls this
    result[:] = [(str(a.arguments[0]), str(a.arguments[1]))
                 for a in m.symbols(atoms=True) if a.match("assigned", 2)]
ctl.solve(on_model=on_model)
# work with the plain tuples in result (the last, best model)
```

This also applies to verification: snapshot the atoms into plain Python inside
`on_model`, then run your checks on the snapshot after solving.

## Section 4: Problem-Solving Pattern Library

### 4.1 Modeling State and Change (NEW - CRITICAL)

#### A. Define Exclusive States (Fluents)
A fluent is a property that changes over time. If the task makes it single-valued, it has at most ONE value at any time.

**Examples of fluents:**
- Location of an object
- Whether a resource is available
- State of a process (idle, running, complete)

**Enforce exclusivity:**
```asp
% Object cannot be in two places
:- at(Obj,Loc1,T), at(Obj,Loc2,T), Loc1 != Loc2.

% Resource cannot be both free and occupied
:- free(R,T), occupied(R,T).

% Process cannot be in multiple states
:- state(P,S1,T), state(P,S2,T), S1 != S2.
```

#### B. Frame Axioms: Persistence vs Change
Frame axioms define what persists. They must NOT fire when an action changes that state.

**Pattern:**
```asp
% State persists IF no action changes it
fluent(Args,T+1) :- fluent(Args,T), time(T+1), 
    not action_that_changes_fluent(Args,T).
```

**Example:**
```asp
% Item location persists if not picked up
item_at(I,X,Y,T+1) :- item_at(I,X,Y,T), time(T+1), 
    not pickup(_,I,T).

% Carrying persists if not put down
carrying(R,I,T+1) :- carrying(R,I,T), time(T+1), 
    not putdown(R,I,T).
```

#### C. Debugging Temporal Models

**Common issues and solutions:**

1. **Invalid state combinations**
   - Check: Are mutually exclusive states enforced?
   - Fix: Add exclusivity constraints

2. **Actions happening without preconditions**
   - Check: Are all preconditions validated?
   - Fix: Add precondition constraints

3. **States not changing after actions**
   - Check: Are effect rules defined?
   - Fix: Add effect rules for each action

4. **UNSAT when solution should exist**
   - Debug: Comment out constraints one by one
   - Test: Create minimal test case
   - Isolate: Use "teleportation" test (bypass actions)

### 4.2 Assignment Problems

**Pattern: Worker-Task Assignment**
```asp
% Each task assigned to exactly one worker
1 { assigned(T,W) : worker(W) } 1 :- task(T).

% Worker capacity constraint
:- worker(W), capacity(W,C), #count { T : assigned(T,W) } > C.
```

### 4.3 Graph Problems

**Pattern: Graph Coloring**
```asp
% Each node gets exactly one color
1 { colored(N,C) : color(C) } 1 :- node(N).

% Adjacent nodes different colors
:- colored(N1,C), colored(N2,C), edge(N1,N2).
```

### 4.4 Scheduling Problems

**CRITICAL: Always Define a Finite Time Horizon**

When your encoding indexes atoms by time (as in most scheduling and planning encodings), you MUST give the time argument a finite domain. Without this, the solver may attempt to explore an infinite search space, leading to grounding errors (`#inf@0`) or extreme slowness.

```asp
% REQUIRED: Define finite time domain first
time(0..max_time).  % Use the problem's latest deadline or a reasonable upper bound
```

**Pattern: Job Scheduling**
```asp
% STEP 1: Define time domain (CRITICAL!)
time(0..20).  % Set based on problem constraints

% STEP 2: Each job starts at exactly one time
1 { start(J,T) : time(T) } 1 :- job(J).

% No time overflow
:- start(J,T), duration(J,D), T+D-1 > 20.

% No overlap
:- start(J1,T1), start(J2,T2), J1 != J2,
   duration(J1,D1), T1 <= T2, T2 < T1+D1.
```

**Why This Matters:**
- Without `time(0..N)`, variables like `T` in `#minimize { T : makespan(T) }` have no bound
- The grounder will produce `#inf@0` errors or create enormous search spaces
- Always use the latest deadline or a reasonable upper bound as your time horizon

### 4.5 Temporal Reasoning with Frame Axioms

**Critical for**: Robot planning, logistics, action sequences

**Complete Pattern for Temporal Problems:**

```asp
% 1. ENTITIES AND TIME
robot(r1). item(i1). time(0..max_time).
location(1..5, 1..5).

% 2. INITIAL STATE
robot_at(r1,1,1,0).
item_at(i1,2,2,0).

% 3. ACTION GENERATION (Choice Rules)
{ move(R,Dir,T) : direction(Dir) } 1 :- robot(R), time(T), T < max_time.
{ pickup(R,I,T) : item(I) } 1 :- robot(R), time(T), T < max_time.

% 4. MUTUAL EXCLUSION (State Constraints)
% Robot cannot be in two places
:- robot_at(R,X1,Y1,T), robot_at(R,X2,Y2,T), (X1,Y1) != (X2,Y2).

% Item cannot be both at location and carried
:- item_at(I,X,Y,T), carrying(_,I,T).

% 5. ACTION PRECONDITIONS
% Cannot move outside grid
:- move(R,up,T), robot_at(R,X,Y,T), Y >= max_y.

% Cannot pickup from different location
:- pickup(R,I,T), robot_at(R,RX,RY,T), item_at(I,IX,IY,T), (RX,RY) != (IX,IY).

% 6. ACTION EFFECTS
% Movement changes robot position
robot_at(R,X,Y+1,T+1) :- move(R,up,T), robot_at(R,X,Y,T).

% Pickup creates carrying relationship
carrying(R,I,T+1) :- pickup(R,I,T).

% Putdown creates item location
item_at(I,X,Y,T+1) :- putdown(R,I,T), robot_at(R,X,Y,T).

% 7. FRAME AXIOMS (Persistence)
% Robot position persists if no movement
robot_at(R,X,Y,T+1) :- robot_at(R,X,Y,T), time(T+1),
    not move(R,up,T), not move(R,down,T), 
    not move(R,left,T), not move(R,right,T).

% Item location persists if not picked up
item_at(I,X,Y,T+1) :- item_at(I,X,Y,T), time(T+1),
    not pickup(_,I,T).

% Carrying persists if not put down
carrying(R,I,T+1) :- carrying(R,I,T), time(T+1),
    not putdown(R,I,T).
```

### 4.6 Combinatorial Puzzles

**Pattern: N-Queens**
```asp
#const n=8.
1 { queen(R,C) : col(C) } 1 :- row(R).
:- queen(R1,C), queen(R2,C), R1 != R2.
:- queen(R1,C1), queen(R2,C2), R1 != R2, |R1-R2| == |C1-C2|.
```

### 4.7 Enforcing Dependent Properties (A implies B)

A common task is to enforce that if one property `P` holds, a corresponding property `Q` must also hold. State the implication directly as a constraint that forbids the premise without the conclusion:

```asp
:- premise(X), not conclusion(X).
```

The constraint only eliminates answer sets; it does not create `conclusion(X)`. Some rule or choice must be able to derive the conclusion, otherwise every answer set containing the premise is removed.

**Example: every order must be shipped by at least one carrier.**
```asp
order(o1;o2). carrier(c1;c2).
{ ships(O, C) : carrier(C) } :- order(O).
shipped(O) :- ships(O, _).
:- order(O), not shipped(O).
```

### 4.8 Default Logic with Negation as Failure

**Pattern: Default Property with Exceptions**

This pattern implements defeasible reasoning where properties hold by default unless exceptions apply:

```asp
% General Pattern:
% A property holds by default...
has_property(X) :- entity(X), not lacks_property(X).

% ...unless a specific exception applies
lacks_property(X) :- exception_condition_1(X).
lacks_property(X) :- exception_condition_2(X).

% Example: Birds fly unless they're penguins or injured
flies(B) :- bird(B), not cannot_fly(B).
cannot_fly(B) :- penguin(B).
cannot_fly(B) :- injured(B).

% Example: Statements are true unless proven false
believed(Statement) :- statement(Statement), not disproven(Statement).
disproven(Statement) :- contradicts(Statement, Fact), proven(Fact).
```

**Key Insight**: The `not` operator implements Closed World Assumption - what cannot be proven true is assumed false.

### 4.9 Sequential Planning Problems (Tower of Hanoi, Blocks World)

**Critical for**: Multi-step sequential planning where exactly ONE action occurs per timestep.

**ANTI-PATTERN: Multiple Simultaneous Actions + Global Count**

This is the most common mistake in planning problems:

```asp
% WRONG: Allows multiple moves per timestep (one per disk!)
{ move(D, P1, P2, T) : peg(P1), peg(P2), P1 != P2 } 1 :- disk(D), time(T), T < max_time.

% Then uses slow global constraint to force total count
:- #count { D, P1, P2, T : move(D, P1, P2, T) } != max_time.
```

**Why this is catastrophically slow:**
1. Generates moves for ALL disks from ANY peg to ANY peg (even illegal ones)
2. Allows up to N simultaneous moves per timestep (one per disk)
3. Uses expensive #count over entire plan to enforce sequence length
4. Creates massive search space that times out

**CORRECT PATTERN: Sequential Actions with Validity Checking**

The key principles:
1. **Define what CAN be moved** (e.g., top disk on a peg)
2. **Choose exactly ONE valid action per timestep**
3. **No global count needed** - sequence length emerges from timesteps

**Complete Tower of Hanoi Example:**

```asp
#const max_time = 7.
disk(1..3). peg(a;b;c).
time(0..max_time-1).  % Action timesteps (0..6 for 7 moves)

% INITIAL STATE
on_peg(1,a,0). on_peg(2,a,0). on_peg(3,a,0).

% --- 1. DEFINE WHAT CAN BE MOVED ---
% A disk is "top" if no smaller disk is on the same peg
top(D, P, T) :- on_peg(D, P, T), not covered(D, P, T).
covered(D, P, T) :- on_peg(D, P, T), on_peg(D2, P, T), D2 < D.

% --- 2. CHOOSE EXACTLY ONE VALID MOVE PER TIMESTEP ---
% At each time T, move exactly one top disk to a different peg
1 { move(D, P1, P2, T) : top(D, P1, T), peg(P2), P1 != P2 } 1 :- time(T).

% --- 3. PRECONDITIONS ---
% Cannot place larger disk on smaller disk
:- move(D, _, P2, T), top(D2, P2, T), D > D2.

% --- 4. EFFECTS ---
% Moved disk is on new peg at T+1
on_peg(D, P2, T+1) :- move(D, _, P2, T).

% --- 5. FRAME AXIOMS ---
% Disks not moved stay on their peg
on_peg(D, P, T+1) :- on_peg(D, P, T), T < max_time, not move(D, P, _, T).

% --- 6. STATE EXCLUSIVITY ---
% Disk cannot be on two pegs
:- on_peg(D, P1, T), on_peg(D, P2, T), P1 != P2.

% --- 7. GOAL ---
% All disks on peg c at final timestep
:- disk(D), not on_peg(D, c, max_time).
```

**Why this is fast:**
- Only generates valid moves (from top disks only)
- Exactly one move per timestep (correctly models sequential plan)
- No expensive global #count constraint
- Search space is minimal and focused

**Key Pattern Elements:**

1. **Define "Valid"**: Use auxiliary predicate (`top/3`) to identify what can be acted upon
2. **One Action Per Time**: `1 { action(...) : valid(...) } 1 :- time(T)`
3. **Constrain at Source**: Only generate moves from valid sources in choice rule
4. **No Global Counts**: Let sequence length emerge from timesteps naturally

**Blocks World Pattern:**

```asp
% Define what can be moved
clear(B,T) :- block(B), time(T), not on(_, B, T).
on_table_space(T) :- time(T), #count { B : on_table(B,T) } < max_table_slots.

% Exactly one move per timestep
1 { move_to_block(B1, B2, T) : clear(B1,T), clear(B2,T), B1 != B2 ;
    move_to_table(B, T) : clear(B,T), on_table_space(T) } 1 :- time(T).
```

**General Takeaway:** For sequential planning, always:
- Define valid actions via auxiliary predicates
- Use `1 { ... } 1 :- time(T)` for exactly one action per timestep
- Avoid generate-and-filter patterns in choice rules
- Eliminate global #count constraints over entire plans

### 4.10 Sequence and Run-Based Constraints

**Critical for**: problems where a sequence (a row of a grid, a shift roster, a route) must contain given runs: consecutive cells/slots with the same property, in a given order.

First decide from the task whether the clues are exhaustive. If they are, every non-background cell belongs to exactly one clued run, and every clued run must occur. If the task says clues are not exhaustive, replace the last constraint below by what the task says about cells outside the runs.

```asp
% clue(I, C, L): the I-th run (I = 1, 2, ...) has color C and length L; color 0 = background
pos(1..n). color(0..k).
1 { cell(P, C) : color(C) } 1 :- pos(P).
% every clued run occurs exactly once
1 { start(I, S) : pos(S), S + L - 1 <= n } 1 :- clue(I, _, L).
% runs in clue order; consecutive runs of the same color need a gap
:- start(I, S1), start(I+1, S2), clue(I, _, L1), S2 < S1 + L1.
:- start(I, S1), start(I+1, S2), clue(I, C, L1), clue(I+1, C, _), S2 = S1 + L1.
% cells of a run have the run's color
in_run(P) :- start(I, S), clue(I, C, L), pos(P), S <= P, P < S + L.
:- start(I, S), clue(I, C, L), pos(P), S <= P, P < S + L, not cell(P, C).
% exhaustive clues: every non-background cell lies in a clued run
:- cell(P, C), C != 0, not in_run(P).
```

For a grid, add the row or column index to `clue`, `start` and `in_run`, and map positions to grid cells.

### 4.11 "Reachable Only After" / Ordered Reachability Constraints

An ordering requirement on reachability has two different readings: (1) there exists some order of visiting the elements that satisfies the requirement (a guessed sequence or path), or (2) each element becomes accessible at the earliest step a stated progression rule allows, and the requirement concerns these earliest steps. Take the reading from the task; if the task does not settle it, state your assumption.

For reading (2), compute earliest accessibility with a time-indexed fixpoint:

```asp
step(0..h).
acc(X, 0) :- start(X).
acc(Y, T+1) :- acc(X, T), edge(X, Y), open(X, Y, T), step(T+1).
acc(X, T+1) :- acc(X, T), step(T+1).                    % persistence
first(X, T) :- acc(X, T), not acc(X, T-1).
```

Define `open/3` from the task's progression rule, then constrain `first/2` as the task requires; whether two elements may become accessible at the same step is part of the task. Verify with a plain-Python simulation of the same process:
repeatedly add everything currently accessible, one step at a time, and check the
required ordering of first-access steps against the problem text — do not reuse
your encoding's ordering predicates in the verifier.

### 4.12 State-Dependent Reachability (Abilities That Grow Along a Walk)

**Critical for**: one agent on directed edges where an edge needs something picked up or done earlier on the same walk (keys, tools, switches). This section asks whether some single walk enters a node; for the step at which each element first becomes accessible under a stated progression rule, see 4.11.

**ANTI-PATTERN: the pooled fixpoint** `reach(Y) :- reach(X), edge(X,Y,I), has(I).` with `has(I)` true once the node holding `I` is reached. It uses every collected item at every reached node, so the set may contain nodes no walk enters: after a one-way edge into a dead end that holds the key, the key still opens edges at the start. A sufficient condition for soundness is that every edge X->Y has a reverse edge Y->X needing no item beyond what X->Y needs; without such an argument, use the state model.

**CORRECT PATTERN: reachability over states (node, items held).** A node is reachable if some single walk from the start enters it. Give each item its own bit; a mask is the set held:

```asp
% item(I,V): V = 1,2,4,... one bit per item. at(I,N): item I lies at node N.
% edge(X,Y,R): X->Y needs every item in mask R (0 = none). start(S). node(N).
gain(N,K) :- node(N), K = #sum { V,I : at(I,N), item(I,V) }.
st(S,K) :- start(S), gain(S,K).
st(Y,M?K) :- st(X,M), edge(X,Y,R), M & R = R, gain(Y,K).   % ? = bitwise or
reachable(N) :- st(N,_).
```

Example: `edge(s,a,0). edge(a,b,0). edge(s,c,1).`, the only item at `b`: the pooled fixpoint reaches `c`, this model does not; with `edge(b,s,0)` both reach all nodes.

**Choosing the bound.** On fixed data the grounder computes this model without horizon or search, at most |nodes| * 2^k states for k items. Use at most 31 items (bit values up to 2^30): clingo integers are 32-bit and wrap silently, so 2^32 becomes 0 and its edge needs nothing. Prefer this model to decide which nodes are reachable, and a time-indexed walk (`at(N,T)`, `holds(I,T)`, as in 4.5 and 4.9) when the walk is the answer (a route, fewest moves); a walk proves reachable only the nodes it enters. For consumables (single-use keys, fuel) the state holds the remaining quantities and, for pickups that do not respawn, whether each is still there.

**In a generator** (layout guessed, every node reachable), add `:- node(N), not reachable(N).` No saturation is needed: `st/2` is positive recursion, so each answer set holds exactly the reachable states of its layout, and constraints may require or forbid reachability. The grounder then grounds every mask the candidate edges allow: keep k small.

**Verification**: the plain-Python verifier simulates the walk over (node, items held), not the pooled fixpoint:

```python
def walk_reach(start, edges, items_at):  # edges: (x, y, frozenset needed)
    s0 = (start, frozenset(items_at.get(start, ())))
    seen, todo = {s0}, [s0]
    while todo:
        x, held = todo.pop()
        for a, y, need in edges:
            if a == x and need <= held:
                s = (y, held | frozenset(items_at.get(y, ())))
                if s not in seen:
                    seen.add(s)
                    todo.append(s)
    return {n for n, _ in seen}
```

## Section 5: Debugging & Advanced Techniques

### 5.1 Efficient Generation: Constrain Choices Early (Anti-Pattern: Generate-and-Filter)

A common performance pitfall is to generate a massive number of candidate solutions in a choice rule and then use separate integrity constraints to filter out the vast majority of invalid ones. This forces the grounder and solver to consider many useless options.

**The Principle: Constrain at the Source.** Build validity checks directly into the generating choice rule itself, so the solver only ever considers valid candidates.

**Anti-Pattern: Generate, then Filter**
This approach generates all combinations and then prunes them.

```asp
% DOMAIN: 100 items, 50 containers. compatible(I,C) defines valid pairs.
item(1..100). container(1..50).
compatible(1,c1). compatible(2,c1). %... many other compatibility facts

% ANTI-PATTERN: Generate all 100*50=5000 possible assignments
{ placed(I,C) : container(C) } 1 :- item(I).

% Then, filter out the invalid ones
:- placed(I,C), not compatible(I,C).
```
**Why it's slow:** The solver must first consider 5,000 potential `placed/2` atoms before eliminating most of them.

**Note: Source Filtering Changes Grounding Size, Not Answer Sets**

Moving a filter into the choice domain does not change which answer sets exist. In particular, it does not avoid an `UNSATISFIABLE` result caused by missing data.

**Example: Assigning Features to Devices**
Suppose you must assign a `feature(F)` to a `device(D)`, but only if a `driver(F, D)` fact exists.

**Generate-and-Filter:**
```asp
% For each feature, choose a device to assign it to.
1 { assign(F, D) : device(D) } 1 :- feature(F).

% Constraint: An assignment is only valid if a driver exists.
:- assign(F,D), not driver(F,D).
```

**Constrained at the Source (same answer sets, smaller grounding):**
```asp
% Only generate assignments where a driver exists
1 { assign(F, D) : device(D), driver(F, D) } 1 :- feature(F).
% No separate constraint needed - only valid pairs are considered
```
**Both versions are UNSAT** if some `feature(f_special)` has **no** `driver(f_special, _)` fact, because `1 { ... } 1` requires one assignment from an empty set of options. Check the data for such gaps before solving, and if the task allows unassigned features, lower the bound to `0 { ... } 1`.

**Good Pattern: Constrain During Generation**
This approach only generates combinations that are already known to be valid.

```asp
% DOMAIN: Same as above.
item(1..100). container(1..50).
compatible(1,c1). compatible(2,c1). %...

% GOOD PATTERN: Only generate assignments (I,C) where compatible(I,C) is true.
{ placed(I,C) : container(C), compatible(I,C) } 1 :- item(I).

% No filter rule is needed.
```
**Why it's fast:** The solver's search space is restricted from the very beginning to only valid pairs. If there are only 200 compatible pairs, it considers 200 options, not 5,000.

**General Takeaway:** Push filtering conditions from the body of separate constraints (`:- ...`) into the domain of the choice rule (`{... : conditions}`).

### 5.2 CRITICAL: Canonical Counting for Symmetric Relations

When counting relationships between pairs of entities (connections, edges, paths), you must ensure each pair is counted **exactly once**. A symmetric definition can lead to double-counting, making cardinality constraints impossible to satisfy.

**The Problem: Double-Counting**

A common mistake is to define a relationship symmetrically, which causes each instance to be counted multiple times:

```asp
% INCORRECT: Double-counts one-way links
% If a -> b is one-way, this creates BOTH oneway(a,b) AND oneway(b,a)
oneway(A, B) :- link(A, B), not link(B, A).
oneway(A, B) :- link(B, A), not link(A, B).

% Counts each one-way link twice
n_oneway(N) :- N = #count { A, B : oneway(A, B) }.
```

**The Solution: Canonical Ordering**

Establish a canonical representation for each unordered pair by enforcing an ordering constraint (typically using `<`). This ensures each pair is represented exactly once. Count ordered (directed) relationships directly; canonicalize only unordered ones.

```asp
% CORRECT: Canonical counting with ordering
% A one-way link between A and B (where A < B) creates exactly ONE atom
oneway_pair(A, B) :- link(A, B), not link(B, A), A < B.
oneway_pair(A, B) :- link(B, A), not link(A, B), A < B.

% Now each one-way link is counted once
n_oneway(N) :- N = #count { A, B : oneway_pair(A, B) }.
```

**Pattern Examples:**

```asp
% Bidirectional connections (canonical form)
bidirectional(A, B) :- A < B, link(A, B), link(B, A).

% Counting edges in undirected graphs
edge_count(N) :- N = #count { V1, V2 : V1 < V2, edge(V1, V2) }.

% Finding isolated pairs
isolated_pair(A, B) :- A < B, entity(A), entity(B),
    not connected(A, B), not connected(B, A).
```

**When to Use This Pattern:**

- Counting bidirectional or one-way connections
- Measuring relationships in undirected graphs
- Any symmetric or pair-based relationship requiring accurate counting
- Whenever you need to distinguish between "relationship exists" and "count of relationships"

### 5.3 CRITICAL: Controlling Cardinality with Choice Rule Bounds

While Section 5.1 focuses on filtering the *domain* of a choice rule, bounds `L { ... } U` control the *number* of atoms chosen from it: an unbounded choice `{ ... }` allows any number, so add bounds when the specification fixes the number (exactly one, at most one, exactly `k`), and leave the choice unbounded when the specification allows several.

#### General Patterns for Cardinality Control

| Goal                                   | ASP Pattern                                                         | Explanation                                            |
| :------------------------------------- | :------------------------------------------------------------------ | :----------------------------------------------------- |
| **Assign a unique property**           | `1 { has_property(X, P) : property(P) } 1 :- entity(X).`             | Each entity `X` must have **exactly one** property `P`.|
| **Model an optional, unique connection** | `0 { connected(X, Y, Type) : conn_type(Type) } 1 :- pair(X, Y).`     | There is **at most one** connection between `X` and `Y`.|
| **Select a fixed number of items**     | `k { selected(I) : item(I) } k :- ...`                              | **Exactly `k`** items must be selected from the domain. |
| **Select a minimum number of items**   | `k { selected(I) : item(I) } :- ...`                                | **At least `k`** items must be selected.               |

### 5.4 Avoiding Grounding Explosion: Decompose Complex Arithmetic (Anti-Pattern: Monolithic Arithmetic)

Writing a single, large arithmetic constraint that involves many independent variables can cause a "grounding explosion." The grounder must instantiate the rule for every possible combination of values for those variables.

**The Principle: Aggregate, Don't Enumerate.** Use auxiliary predicates and aggregates (`#sum`, `#count`, etc.) to compute intermediate results. Then, write simpler constraints over those results.

**Anti-Pattern: Monolithic Arithmetic Constraint**
This approach forces the grounder to iterate through all value combinations.

```asp
% DOMAIN: Assign a value from 1..10 to four variables a,b,c,d.
var(a;b;c;d). value(1..10).
1 { assign(V, N) : value(N) } 1 :- var(V).

% ANTI-PATTERN: Compare sums directly.
% This requires grounding for every combination of N1,N2,N3,N4 from 1..10.
% That's 10 * 10 * 10 * 10 = 10,000 ground rules.
:- assign(a, N1), assign(b, N2), assign(c, N3), assign(d, N4),
   N1 + N2 != N3 + N4.
```
**Why it's slow:** The grounder creates a massive number of rules that are computationally expensive to process, even if the logic is simple.

**Good Pattern: Decompose with Aggregates**
This approach computes the sums first, then compares the two results.

```asp
% DOMAIN: Same as above.
var(a;b;c;d). value(1..10).
1 { assign(V, N) : value(N) } 1 :- var(V).

% GOOD PATTERN: Use #sum to calculate intermediate values.
sum_ab(S) :- S = #sum { N,V : assign(V,N), V=(a;b) }.
sum_cd(S) :- S = #sum { N,V : assign(V,N), V=(c;d) }.

% Now, constrain the two resulting sums. This generates very few ground rules.
:- sum_ab(S1), sum_cd(S2), S1 != S2.
```
**Why it's fast:** The `#sum` aggregate is highly optimized. The solver computes each sum just once. The final constraint only compares the two resulting sum values, avoiding the combinatorial explosion.

**General Takeaway:** Instead of writing complex arithmetic expressions with many variables in a single rule body, use aggregates to compute sub-expressions and constrain their results.

### Debugging Temporal Models (CRITICAL)

1. **Test state exclusivity first**
   ```asp
   % Add test constraints to verify exclusivity
   :- item_at(test_item,_,_,5), carrying(_,test_item,5).
   ```

2. **Isolate action logic**
   ```asp
   % Test if goals are achievable without actions
   item_at(I,X,Y,max_time) :- item_destination(I,X,Y).
   ```

3. **Trace single actions**
   ```asp
   % Force specific action to test effects
   move(r1,up,0).
   ```

4. **Use clingo's debugging features**
   ```python
   # Show ground atoms
   ctl.ground([("base", [])])
   for atom in ctl.symbolic_atoms:
       if "item_at" in str(atom.symbol):
           print(atom.symbol)
   ```

### Common Errors and Solutions

1. **"Unsafe variable" errors**:
   - Add positive predicate defining variable's domain

2. **"Syntax error, unexpected #sum"**:
   - Move aggregate to body or optimization

3. **No answer sets (UNSAT)**:
   - Check mutual exclusivity constraints
   - Verify action preconditions aren't too restrictive
   - Test minimal cases

4. **Invalid plans/solutions**:
   - Check state exclusivity enforcement
   - Verify frame axioms and action effects

### Best Practices

1. **Start with state model**: Define fluents and exclusivity first
2. **Test incrementally**: Add one action type at a time
3. **Use meaningful names**: `robot_at(r1,3,4,5)` not `p(1,3,4,5)`
4. **Document assumptions**: Comment complex constraints
5. **Verify exclusivity**: Always enforce mutual exclusion for fluents