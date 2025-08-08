# URL Parsing Task

## Task
Parse URLs from text and extract their components (protocol, domain, path, query parameters).

## Input
```
text.txt:
Visit our website at https://www.example.com/products?category=electronics&sort=price
Documentation: http://docs.api-service.io/v2/guide#section-auth
GitHub repo: https://github.com/user/project
Invalid: htp://broken.url and www.no-protocol.com
FTP resource: ftp://files.example.org/downloads/file.zip
```

## Requirements
- Extract valid URLs with protocols (http, https, ftp)
- Parse each URL into components:
  - protocol
  - domain
  - path (if present)
  - query parameters (if present)
  - fragment/anchor (if present)
- Return as a list of dictionaries

## Expected Output
```python
[
    {
        'url': 'https://www.example.com/products?category=electronics&sort=price',
        'protocol': 'https',
        'domain': 'www.example.com',
        'path': '/products',
        'query': {'category': 'electronics', 'sort': 'price'},
        'fragment': None
    },
    {
        'url': 'http://docs.api-service.io/v2/guide#section-auth',
        'protocol': 'http',
        'domain': 'docs.api-service.io',
        'path': '/v2/guide',
        'query': {},
        'fragment': 'section-auth'
    },
    {
        'url': 'https://github.com/user/project',
        'protocol': 'https',
        'domain': 'github.com',
        'path': '/user/project',
        'query': {},
        'fragment': None
    },
    {
        'url': 'ftp://files.example.org/downloads/file.zip',
        'protocol': 'ftp',
        'domain': 'files.example.org',
        'path': '/downloads/file.zip',
        'query': {},
        'fragment': None
    }
]
```