# Phone Number Validation Task

## Task
Validate and extract US phone numbers from text, normalizing them to a standard format.

## Input
```
text.txt:
Call us at (555) 123-4567 or 555.987.6543 for assistance.
Alternative numbers: 555-444-3333, 1-800-555-1212.
International: +1 555 888 9999
Invalid: 12345, 555-12-3456, (555)1234567890
```

## Requirements
- Match valid US phone numbers in various formats:
  - (XXX) XXX-XXXX
  - XXX-XXX-XXXX
  - XXX.XXX.XXXX
  - 1-XXX-XXX-XXXX
  - +1 XXX XXX XXXX
- Normalize all matches to format: (XXX) XXX-XXXX
- Validate that area codes don't start with 0 or 1

## Expected Output
```python
[
    '(555) 123-4567',
    '(555) 987-6543',
    '(555) 444-3333',
    '(800) 555-1212',
    '(555) 888-9999'
]
```