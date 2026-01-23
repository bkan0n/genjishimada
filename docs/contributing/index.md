# Contributing

Thank you for your interest in contributing to Genji Shimada! This guide will help you get started.

## Quick Start

1. **Fork and clone** the repository
2. **Install dependencies**: `just setup`
3. **Create a branch** for your changes
4. **Make your changes** and test them
5. **Submit a pull request**

## Code of Conduct

Be respectful, constructive, and welcoming to all contributors. We're building this together.

## Getting Started

### Prerequisites

Ensure you have the required tools installed:

- Python 3.13+
- uv (package manager)
- Docker and Docker Compose (for local infrastructure)
- just (task runner)

See the [Installation Guide](../getting-started/installation.md) for detailed setup instructions.

### Local Development Setup

1. **Install dependencies**:
   ```bash
   just setup
   ```

2. **Configure environment**:
   ```bash
   cp .env.local.example .env.local
   # Edit .env.local with your Discord token
   ```

3. **Start infrastructure** (PostgreSQL, RabbitMQ, MinIO):
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

4. **Create MinIO bucket**:
   ```bash
   mc alias set local http://localhost:9000 genji local_dev_password
   mc mb local/genji-parkour-images
   ```

5. **Import database** (optional):
   ```bash
   ./scripts/import-db-from-vps.sh dev
   ```

6. **Run API and bot**:
   ```bash
   # Terminal 1
   just run-api

   # Terminal 2
   just run-bot
   ```

### Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes** to the codebase

3. **Run linters**:
   ```bash
   just lint-all
   ```

4. **Run tests**:
   ```bash
   just test-all
   ```

5. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Add feature: your feature description"
   ```

6. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Open a pull request** on GitHub

## Project Structure

```
genjishimada/
├── apps/
│   ├── api/          # Litestar REST API
│   │   ├── di/       # Business logic (DI modules)
│   │   ├── routes/   # HTTP route handlers
│   │   ├── middleware/ # Auth and request processing
│   │   └── tests/    # API tests
│   └── bot/          # Discord bot
│       ├── core/     # Bot core (Genji class)
│       ├── extensions/ # Feature modules (cogs)
│       └── docs/     # Bot-specific docs (legacy)
├── libs/
│   └── sdk/          # Shared msgspec models
│       └── src/genjishimada_sdk/
├── docs/             # Documentation (MkDocs)
├── infra/            # Infrastructure configs
└── ops/              # Operations scripts
```

## Coding Standards

### Python Style

We use **Ruff** for formatting and linting, and **BasedPyright** for type checking.

**Key rules**:

- Line length: 120 characters
- Docstring style: Google
- Type hints required for all function signatures
- Import sorting enabled

Run linters:

```bash
just lint-all
```

### Type Annotations

All functions must have type annotations:

```python
# Good
async def get_map(map_id: int) -> MapResponse:
    ...


# Bad
async def get_map(map_id):
    ...
```

### Docstrings

Use Google-style docstrings:

```python
def process_completion(completion_id: int, user_id: int) -> bool:
    """Process a user's completion submission.

    Args:
        completion_id: The unique ID of the completion.
        user_id: The ID of the user who submitted the completion.

    Returns:
        True if processing succeeded, False otherwise.

    Raises:
        ValueError: If the completion_id is invalid.
    """
    ...
```

### Error Handling

Use custom exceptions from `utilities/errors.py`:

```python
from utilities.errors import CustomHTTPException

if not map_exists:
    raise CustomHTTPException(
        status_code=404,
        detail="Map not found"
    )
```

## Testing

### Writing Tests

Tests are located in `apps/api/tests/`.

**Example**:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_map(client: AsyncClient):
    response = await client.get("/maps/1")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Map"
```

### Running Tests

Run all tests:

```bash
just test-all
```

Run API tests only:

```bash
just test-api
```

Run specific test file:

```bash
uv run --project apps/api pytest apps/api/tests/test_maps.py
```

### Test Database

Tests use an isolated PostgreSQL database, automatically created and torn down by `pytest-databases`.

### Mocking

Use `pytest` fixtures for mocking:

```python
@pytest.fixture
def mock_rabbitmq():
    return AsyncMock()
```

## Database Migrations

Migrations are **manual**. There is no migration runner in this repo.

### Creating Migrations

1. Create a new SQL file in `apps/api/migrations/`:
   ```bash
   touch apps/api/migrations/0004_add_new_feature.sql
   ```

2. Write the migration:
   ```sql
   CREATE TABLE new_feature (
       id serial PRIMARY KEY,
       name text NOT NULL
   );
   ```

3. Apply the migration manually using your preferred Postgres client. Example (local database):
   ```bash
   docker exec -i genjishimada-db-local psql -U genji -d genjishimada < apps/api/migrations/0004_add_new_feature.sql
   ```

### Migration Guidelines

- Name files sequentially: `0001`, `0002`, etc.
- Include comments explaining the purpose
- Test on a copy of production data
- Keep migrations small and focused

## Pull Request Process

### Before Submitting

1. **Lint your code**: `just lint-all`
2. **Run tests**: `just test-all`
3. **Update documentation** if needed
4. **Write a clear commit message**

### PR Title Format

Use conventional commit format:

- `feat: Add new map search endpoint`
- `fix: Resolve completion verification bug`
- `docs: Update API authentication guide`
- `refactor: Simplify DI module structure`
- `test: Add tests for lootbox system`

### PR Description

Include:

- **What**: What does this PR do?
- **Why**: Why is this change needed?
- **How**: How does it work?
- **Testing**: How was it tested?

### Review Process

1. A maintainer will review your PR
2. Address any requested changes
3. Once approved, your PR will be merged

## Areas to Contribute

### Good First Issues

Look for issues labeled `good first issue` on GitHub.

### Feature Requests

Have an idea? Open an issue to discuss it first.

### Documentation

Improve or expand the documentation in the `docs/` directory.

### Bug Fixes

Found a bug? Submit a fix with tests.

## Communication

- **GitHub Issues**: For bug reports and feature requests
- **Discord**: Join the [Genji Parkour server](https://dsc.gg/genjiparkour) for discussions

## Next Steps

- [Development Workflow](workflow.md) - Detailed workflow guide
- [Documentation Guide](documentation.md) - Contributing to docs
- [Getting Started](../getting-started/index.md) - Set up your environment
