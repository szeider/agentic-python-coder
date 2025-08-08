## Packages
- re

# Regular Expression Guide

This guide provides common regex patterns and examples for text processing tasks.

## Common Patterns

### Email Addresses
```python
import re

# Match email addresses
email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
emails = re.findall(email_pattern, text, re.IGNORECASE)
```

### Phone Numbers
```python
# US phone numbers - matches: (555) 123-4567, 555-123-4567, 555.123.4567
us_phone_pattern = r'(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})'
matches = re.findall(us_phone_pattern, text)

# Format as (area) prefix-line
formatted_phones = [f"({area}) {prefix}-{line}" for area, prefix, line in matches]
```

### URLs
```python
# Match HTTP(S) URLs
url_pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
urls = re.findall(url_pattern, text)
```

### Dates
```python
# ISO format (YYYY-MM-DD)
iso_date_pattern = r'\d{4}-\d{2}-\d{2}'

# US format (MM/DD/YYYY)
us_date_pattern = r'\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12][0-9]|3[01])/\d{2,4}\b'

# EU format (DD/MM/YYYY)
eu_date_pattern = r'\b(?:0?[1-9]|[12][0-9]|3[01])/(?:0?[1-9]|1[0-2])/\d{2,4}\b'
```

## Useful Functions

### Testing Patterns
```python
def test_pattern(pattern, text, flags=0):
    """Test a regex pattern and show all matches with positions."""
    import re
    
    try:
        for match in re.finditer(pattern, text, flags):
            print(f"Found '{match.group()}' at position {match.span()}")
            if match.groups():
                print(f"  Groups: {match.groups()}")
    except re.error as e:
        print(f"Invalid pattern: {e}")
```

### Validating Patterns
```python
def validate_pattern(pattern):
    """Check if a regex pattern is valid."""
    import re
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False
```

### Cleaning Text
```python
# Remove extra whitespace
clean_text = re.sub(r'\s+', ' ', text).strip()

# Remove special characters (keep only alphanumeric and spaces)
clean_text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
```

## Regex Flags

- `re.IGNORECASE` (re.I) - Case-insensitive matching
- `re.MULTILINE` (re.M) - ^ and $ match start/end of each line
- `re.DOTALL` (re.S) - . matches newline characters
- `re.VERBOSE` (re.X) - Allow comments and whitespace in pattern

### Example with flags:
```python
# Case-insensitive email search
emails = re.findall(email_pattern, text, re.IGNORECASE)

# Multiline pattern with comments
pattern = re.compile(r'''
    \b              # Word boundary
    [A-Z][a-z]+     # Capitalized word
    \s+             # One or more spaces
    [A-Z][a-z]+     # Another capitalized word
    \b              # Word boundary
''', re.VERBOSE)
```

## Tips

1. Always use raw strings (r'...') for regex patterns to avoid escape issues
2. Test patterns with sample data before using in production
3. Use online tools like regex101.com to debug complex patterns
4. Consider using re.compile() for patterns used multiple times
5. Be careful with greedy vs non-greedy quantifiers (* vs *?, + vs +?)