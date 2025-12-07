# Email Extraction Task

## Task
Extract all email addresses from the given text file and return them as a list.

## Input
```
text.txt:
Hello, you can reach me at john.doe@example.com or jane_smith@company.co.uk.
For urgent matters, contact support@help-desk.org or admin+filters@subdomain.example.net.
Invalid emails like @example.com or user@ should not be matched.
```

## Requirements
- Extract valid email addresses only
- Handle common email formats including:
  - Dots and underscores in local part
  - Plus addressing (user+tag@domain)
  - Hyphens in domain
  - Multiple subdomains
- Return as a Python list

## Expected Output
```python
[
    'john.doe@example.com',
    'jane_smith@company.co.uk',
    'support@help-desk.org',
    'admin+filters@subdomain.example.net'
]
```