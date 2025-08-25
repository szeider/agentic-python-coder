# Answer Set Programming (ASP) Task - v03

## Section 1: Mission Briefing & Core Requirements

### Primary Goal
Produce a solution using Answer Set Programming (ASP) that correctly models and solves the problem using the clingo Python API.

### Non-Negotiable Requirements
1. **Tool**: You MUST use the clingo Python API for modeling and solving
2. **Execution Time**: Your script must complete within 10 seconds
3. **Output Format**: Print the final solution as a single JSON object to stdout
4. **Task Management**: You MUST use the TodoWrite tool at the START of your work:
   - Create initial todo list with at least 5-8 tasks
   - Update status as you progress (pending → in_progress → completed)
   - Add new tasks if needed during execution
5. **Error Documentation**: Create `feedback.md` for environment/specification issues

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
☐ 5. **Output format correct** - JSON output with appropriate structure
☐ 6. **Predicates meaningful** - Clear names that reflect the problem domain
☐ 7. **Constraints verified** - All problem constraints are encoded
☐ 8. **File written** - Create `solution.py` with complete working code

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

#### B. Structure of Rules and Facts
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

**FUNDAMENTAL RULE**: Every variable appearing in a rule MUST be grounded by appearing in at least one positive, non-aggregate, non-arithmetic literal in the rule's body.

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

### MANDATORY RULE: Aggregate Placement

**Aggregates (#count, #sum, #min, #max) can ONLY be used:**
- In the BODY of a rule (for conditions)
- In #minimize/#maximize statements
- NEVER in the HEAD of a regular rule

**Why**: Rule heads generate new facts, while aggregates compute over existing facts.

```asp
% CORRECT - Aggregate in constraint body
:- #count { X : selected(X) } > 5.

% CORRECT - Aggregate in optimization
#minimize { Cost,X : selected(X), cost(X,Cost) }.

% INCORRECT - Cannot use aggregate in rule head
% total(#sum{C,X : cost(X,C)}) :- ...  % SYNTAX ERROR!

% CORRECT - Use auxiliary predicates instead
total(T) :- T = #sum{C,X : selected(X), cost(X,C)}.
```

### MANDATORY RULE: State Exclusivity (Fluents)

**FUNDAMENTAL PRINCIPLE**: A property that changes over time (a "fluent") can only have ONE value at any given time. You MUST enforce mutual exclusivity.

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

#### Step 0: Initialize Task Management (MANDATORY - DO THIS FIRST!)

**You MUST start by using TodoWrite with a task list like this:**
```
1. Analyze problem and identify constraints
2. Design ASP predicates and model structure  
3. Implement facts and choice rules
4. Add constraints and optimization
5. Solve and extract solution
6. Format output as JSON
7. Test and verify solution
```

Update task status throughout:
- Mark current task as `in_progress` before starting it
- Mark as `completed` when done
- Add new tasks if you discover additional work

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

### When to Create feedback.md

Create `feedback.md` ONLY for:
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
:~ delayed(Task). [1@2]        % Prefer on-time, priority 2
:~ cost(C). [C@1]              % Minimize cost, priority 1
```

### 2.7 Multi-Objective Optimization

When using multiple `#minimize` or `#maximize` statements, clingo optimizes level-by-level in order:

```asp
% Optimized in this order:
#maximize { Score*3 : ai_performance(Score) }.    % First priority
#maximize { Score*2 : gaming_score(Score) }.      % Second priority  
#maximize { Score : user_preference(Score) }.     % Third priority
#minimize { Cost : total_cost(Cost) }.            % Fourth priority
```

This allows sophisticated trade-off balancing without complex weight tuning.

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
    # Process atoms into solution
    
result = ctl.solve(on_model=on_model)

# Output
if result.satisfiable:
    print(json.dumps(solution))
else:
    print(json.dumps({"error": "No solution exists"}))
```

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

## Section 4: Problem-Solving Pattern Library

### 4.1 Modeling State and Change (NEW - CRITICAL)

#### A. Define Exclusive States (Fluents)
A fluent is a property that changes over time. It can only have ONE value at any time.

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
:- worker(W), #count { T : assigned(T,W) } > capacity(W).
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

**Pattern: Job Scheduling**
```asp
% Each job starts at exactly one time
1 { start(J,T) : time(T) } 1 :- job(J).

% No time overflow
:- start(J,T), duration(J,D), T+D-1 > horizon.

% No overlap
:- start(J1,T1), start(J2,T2), J1 != J2,
   duration(J1,D1), T1 <= T2, T2 < T1+D1.
```

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

### 4.6 Default Logic with Negation as Failure

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

## Section 5: Debugging & Advanced Techniques

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
   # Show grounded rules
   ctl.ground([("base", [])])
   for atom in ctl.symbolic_atoms:
       if "item_at" in str(atom):
           print(atom)
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