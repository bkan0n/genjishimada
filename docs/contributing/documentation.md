# Documentation Guide

How to contribute to and maintain the Genji Shimada documentation.

## Overview

The documentation is built with **MkDocs Material** and hosted on GitHub Pages at [docs.genji.pk](https://docs.genji.pk).

## Documentation Structure

```
docs/
├── index.md                    # Home page
├── domain/                     # Domain overview
├── services/                   # Service-level docs
├── getting-started/            # Installation and quickstart
├── bot/                        # Bot documentation
├── api/                        # API documentation
├── sdk/                        # SDK documentation
├── operations/                 # Infrastructure and deployment
├── contributing/               # Contribution guides
├── stylesheets/
│   └── extra.css               # Custom Tailwind colors
└── openapi.json                # Generated OpenAPI spec
```

## Local Development

### Preview Documentation

Serve the docs locally with live reload:

```bash
just docs-serve
```

Visit `http://127.0.0.1:8000` to view the documentation.

### Build Documentation

Generate the OpenAPI spec and build the site:

```bash
uv run --project apps/api python scripts/generate_openapi.py
uv run --project docs mkdocs build
```

Output is in `site/`.

## Writing Documentation

### Markdown Basics

Use GitHub-flavored Markdown with MkDocs Material extensions.

**Headings**:

```markdown
# H1 - Page Title
## H2 - Section
### H3 - Subsection
```

**Links**:

```markdown
[Link text](../other-page.md)
[External link](https://example.com)
```

**Code blocks**:

````markdown
```python
def hello():
    print("Hello, world!")
```
````

**Inline code**:

```markdown
Use `just run-api` to start the server.
```

### MkDocs Material Features

#### Admonitions

Highlight important information:

```markdown
!!! note
    This is a note.

!!! warning
    This is a warning.

!!! tip
    This is a tip.

!!! danger
    This is a danger alert.
```

Result:

!!! note
    This is a note.

#### Code Annotations

Add explanations to code blocks:

````markdown
```python
def process(data):  # (1)!
    return data * 2
```

1. Multiply the input by 2
````
