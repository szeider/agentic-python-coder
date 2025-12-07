# Circuit Diagnosis with Minimal Assumptions

## Problem Description

Diagnose a simple digital circuit to find which components must be faulty to explain observed behavior. This demonstrates ASP's ability to find minimal explanations through stable model semantics.

## Circuit Description

A circuit with 3 AND gates and 2 OR gates:
- AND1: inputs A, B → output X
- AND2: inputs C, D → output Y  
- AND3: inputs E, F → output Z
- OR1: inputs X, Y → output P
- OR2: inputs Y, Z → output Q

## Observations

Given inputs and expected vs actual outputs:
- Inputs: A=1, B=1, C=1, D=1, E=0, F=1
- Expected: X=1, Y=1, Z=0, P=1, Q=1
- Observed: X=1, Y=0, Z=0, P=1, Q=0

The observed Y=0 and Q=0 differ from expected values.

## Task

Find the minimal set of components that must be faulty to explain the observations. Use ASP's optimization capabilities to minimize the number of faulty components.

## Expected Output

```json
{
  "diagnoses": [
    {
      "faulty_components": ["AND2"],
      "explanation": "AND2 is faulty, producing 0 instead of 1, which explains Y=0 and propagates to Q=0"
    }
  ],
  "num_faults": 1,
  "verification": {
    "X": {"expected": 1, "with_fault": 1, "ok": true},
    "Y": {"expected": 1, "with_fault": 0, "ok": true},
    "Z": {"expected": 0, "with_fault": 0, "ok": true},
    "P": {"expected": 1, "with_fault": 1, "ok": true},
    "Q": {"expected": 1, "with_fault": 0, "ok": true}
  }
}
```

## Why This Showcases ASP

This problem demonstrates:
- **Abductive reasoning**: Finding explanations for observations
- **Minimal models**: Using optimization to find simplest explanations
- **Choice rules**: Choosing which components might be faulty
- **Integrity constraints**: Ensuring consistency with observations
- **Stable model semantics**: Each diagnosis is a stable model