# Bird Flight Reasoning with Defaults and Exceptions

## Problem Description

Model a knowledge base about birds and their ability to fly, demonstrating default reasoning with exceptions using ASP's stable model semantics.

Given the following knowledge:
- Birds normally fly (default rule)
- Penguins are birds
- Ostriches are birds  
- Penguins do not fly (exception)
- Ostriches do not fly (exception)
- Tweety is a bird
- Opus is a penguin
- Speedy is an ostrich
- Eagles are birds
- Eddie is an eagle

Determine which creatures can fly using:
1. Default reasoning (birds fly unless proven otherwise)
2. Inheritance with exceptions
3. Stable model semantics for handling contradictions

## Expected Output

The solution should provide:
- A list of all creatures and whether they can fly
- Justification based on the reasoning chain
- Demonstration of how exceptions override defaults

Format as JSON:
```json
{
  "creatures": [
    {"name": "tweety", "type": "bird", "flies": true, "reason": "default - birds fly"},
    {"name": "opus", "type": "penguin", "flies": false, "reason": "exception - penguins don't fly"},
    {"name": "speedy", "type": "ostrich", "flies": false, "reason": "exception - ostriches don't fly"},
    {"name": "eddie", "type": "eagle", "flies": true, "reason": "default - birds fly"}
  ]
}
```

## Why This Showcases ASP

This problem demonstrates:
- **Negation as failure**: Birds fly unless we can prove they don't
- **Stable model semantics**: Handling potentially conflicting rules
- **Default logic**: General rules with specific exceptions
- **Non-monotonic reasoning**: Adding new information can retract previous conclusions