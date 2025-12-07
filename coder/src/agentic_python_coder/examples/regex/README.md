# Regex Examples

Text processing examples using Python regular expressions.

## Quick Start

```bash
# Extract emails from text
cd sample_tasks
coder --project ../regex.md email_extraction.md

# Validate phone numbers
coder --project ../regex.md phone_validation.md

# Parse URLs
coder --project ../regex.md url_parsing.md
```

## What's Included

The `regex.md` project template provides:
- Common regex patterns (email, phone, URL, IP)
- Python regex best practices
- Text processing techniques

## Sample Tasks

- **email_extraction.md** - Extract and validate email addresses
- **phone_validation.md** - Find and normalize US phone numbers
- **url_parsing.md** - Extract and parse URLs into components

## Create Your Own

Write a task file with:
1. What to extract/validate
2. Sample input data
3. Expected output format

Example:
```
# Extract Product Codes

## Task
Extract product codes like: EL-1234-AB (2-4 letters, 4 digits, 2 letters)

## Input
inventory.txt with lines like:
- "Widget A (EL-1234-AB) - In stock"

## Output
List of codes: ['EL-1234-AB']
```

Then run:
```bash
coder --project regex.md your_task.md
```

## Common Patterns

| Pattern | Example |
|---------|---------|
| Email | `[\w\.-]+@[\w\.-]+\.\w+` |
| US Phone | `\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}` |
| URL | `https?://[\w\.-]+\.\w+[/\w\.-]*` |
| IPv4 | `\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}` |