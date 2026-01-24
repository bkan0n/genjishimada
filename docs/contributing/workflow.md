# Development Workflow

Detailed guide for developing features and fixing bugs in Genji Shimada.

## Setting Up Your Environment

### 1. Fork the Repository

Click "Fork" on GitHub to create your own copy:

```
https://github.com/bkan0n/genjishimada
```

### 2. Clone Your Fork

```bash
git clone https://github.com/YOUR_USERNAME/genjishimada.git
cd genjishimada
```

### 3. Add Upstream Remote

```bash
git remote add upstream https://github.com/bkan0n/genjishimada.git
```

### 4. Install Dependencies

```bash
just setup
```

### 5. Configure Environment

Copy the local environment template:

```bash
cp .env.local.example .env.local
```

Edit `.env.local` with your Discord bot token and other settings.

### 6. Start Infrastructure

```bash
docker compose -f docker-compose.local.yml up -d
```

This starts PostgreSQL, RabbitMQ, and MinIO for local development.

## Daily Workflow

### 1. Sync with Upstream

Before starting work, sync your fork:

```bash
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
```

### 2. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

**Branch naming conventions**:

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test improvements

### 3. Make Changes

Edit code, add tests, update documentation.

### 4. Run Linters

```bash
just lint-all
```

This runs:

- Ruff (formatting and linting)
- BasedPyright (type checking)

**Fix linting issues**:

```bash
# Format code
uv run ruff format .

# Auto-fix linting issues
uv run ruff check --fix .
```

### 5. Run Tests

```bash
just test-all
```

For faster iteration, run specific tests:

```bash
# API tests only
just test-api

# Specific test file
uv run pytest apps/api/tests/test_maps.py

# Specific test function
uv run pytest apps/api/tests/test_maps.py::test_get_map
```

### 6. Commit Changes

Write clear, descriptive commit messages:

```bash
git add .
git commit -m "feat: add map search endpoint

- Add /maps/search route with query parameters
- Implement full-text search using PostgreSQL
- Add tests for search functionality
"
```

**Commit message format**:

```
<type>: <short description>

<detailed description>

<footer (optional)>
```

**Types**:

- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation
- `refactor` - Code refactoring
- `test` - Test improvements
- `chore` - Maintenance tasks

### 7. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 8. Open a Pull Request

1. Go to your fork on GitHub
2. Click "Compare & pull request"
3. Fill out the PR template
4. Submit the PR

## Working on the API

### Project Structure

```
apps/api/
├── di/                # Business logic (DI modules)
│   ├── base.py        # BaseService with RabbitMQ publishing
│   ├── auth.py        # Authentication logic
│   ├── maps.py        # Map CRUD operations
│   └── completions.py # Completion tracking
├── routes/            # HTTP route handlers
│   ├── maps/          # Map-related routes
│   └── completions.py # Completion endpoints
├── middleware/        # Auth and request processing
│   ├── auth.py        # CustomAuthenticationMiddleware
│   └── guards.py      # Scope guards
├── utilities/         # Shared utilities
│   └── errors.py      # Custom exceptions
└── tests/             # API tests
```

### Adding a New Endpoint

1. **Define the route handler** in `routes/`:

   ```python
   from litestar import get
   from genjishimada_sdk.maps import MapResponse

   @get("/maps/{map_id:int}")
   async def get_map(map_id: int, conn: Connection) -> MapResponse:
       map_data = await maps_service.get_map(conn, map_id)
       return map_data
   ```

2. **Implement business logic** in `di/`:

   ```python
   from asyncpg import Connection
   from genjishimada_sdk.maps import MapResponse

   async def get_map(conn: Connection, map_id: int) -> MapResponse:
       row = await conn.fetchrow(
           "SELECT * FROM maps.maps WHERE id = $1",
           map_id
       )
       if not row:
           raise CustomHTTPException(404, "Map not found")
       return MapResponse(**row)
   ```

3. **Add tests** in `tests/`:

   ```python
   import pytest
   from httpx import AsyncClient

   @pytest.mark.asyncio
   async def test_get_map(client: AsyncClient):
       response = await client.get("/api/v3/maps/1")
       assert response.status_code == 200
   ```

4. **Run tests**:

   ```bash
   just test-api
   ```

### Database Queries

Use AsyncPG with parameterized queries:

```python
# Good - parameterized query
row = await conn.fetchrow(
    "SELECT * FROM maps.maps WHERE id = $1",
    map_id
)

# Bad - SQL injection risk
row = await conn.fetchrow(
    f"SELECT * FROM maps.maps WHERE id = {map_id}"
)
```

### Publishing Messages

Use `BaseService.publish_message()`:

```python
from di.base import BaseService
from genjishimada_sdk.completions import CompletionCreatedEvent


class CompletionHandler(BaseService):
    async def create_completion(self, user_id: int, map_id: int) -> int:
        # Create in database
        completion_id = await insert_completion(...)

        # Publish event
        event = CompletionCreatedEvent(
            completion_id=completion_id,
        )
        await self.publish_message(
            queue_name="api.completion.submission",
            message=event,
            message_id=f"completion-{completion_id}",
        )

        return completion_id
```

## Working on the Bot

### Project Structure

```
apps/bot/
├── core/
│   └── genji.py       # Main bot class
├── extensions/        # Feature modules (cogs)
│   ├── rabbit.py      # RabbitMQ service
│   ├── api_service.py # API client
│   └── completions.py # Completion handlers
└── configs/           # Configuration files
    ├── dev.toml
    └── prod.toml
```

### Adding a Queue Consumer

1. **Define the consumer** in an extension:

   ```python
   from extensions._queue_registry import queue_consumer
   from genjishimada_sdk.completions import CompletionCreatedEvent

   @queue_consumer(
       "api.completion.submission",
       struct_type=CompletionCreatedEvent,
       idempotent=True
   )
   async def handle_completion(
       self,
       event: CompletionCreatedEvent,
       message: AbstractIncomingMessage,
   ) -> None:
       # Send Discord notification
       channel = self.bot.get_channel(COMPLETION_CHANNEL_ID)
       await channel.send(f"New completion: {event.completion_id}")
   ```

2. **Test manually**:

   Trigger the event from the API and verify the bot processes it.

### Calling the API

Use the shared `APIService` attached to the bot:

```python
async def get_user(user_id: int):
    return await bot.api.get_user(user_id)
```

## Working on the SDK

### Adding a New Model

1. **Define the model** in `libs/sdk/src/genjishimada_sdk/`:

   ```python
   import msgspec

   class Achievement(msgspec.Struct):
       id: int
       name: str
       description: str
       icon_url: str | None
       xp_reward: int
   ```

2. **Export from `__init__.py`**:

   ```python
   from .achievements import Achievement

   __all__ = ["Achievement", ...]
   ```

3. **Use in API and bot**:

   ```python
   from genjishimada_sdk import Achievement

   achievement = Achievement(
       id=1,
       name="First Completion",
       description="Complete your first map",
       icon_url=None,
       xp_reward=100,
   )
   ```

4. **Run linters**:

   ```bash
   just lint-sdk
   ```

## Debugging

### API Debugging

1. **Add debug logging**:

   ```python
   import logging

   logger = logging.getLogger(__name__)
   logger.debug(f"Processing completion: {completion_id}")
   ```

2. **Run with debug mode**:

   ```bash
   cd apps/api
   uv run litestar run --debug
   ```

3. **Check logs**:

   Logs appear in the terminal.

### Bot Debugging

1. **Add debug logging**:

   ```python
   import logging

   logger = logging.getLogger(__name__)
   logger.debug(f"Received event: {event}")
   ```

2. **Run the bot**:

   ```bash
   just run-bot
   ```

3. **Check logs**:

   Logs appear in the terminal.

### Database Debugging

1. **Connect to PostgreSQL**:

   ```bash
   docker exec -it genjishimada-db-local psql -U genji -d genjishimada
   ```

2. **Run queries**:

   ```sql
   SELECT * FROM maps.maps LIMIT 10;
   ```

## Common Issues

### Import Errors

If you see import errors, re-sync dependencies:

```bash
just sync
```

### Database Connection Failed

Ensure Docker services are running:

```bash
docker compose -f docker-compose.local.yml ps
```

### Tests Failing

Run tests with verbose output:

```bash
uv run pytest -vv apps/api/tests/
```

### Type Errors

Run BasedPyright to see all type errors:

```bash
uv run basedpyright apps/api
```

## Next Steps

- [Contributing Guide](index.md) - General contribution guidelines
- [Documentation Guide](documentation.md) - Update documentation
- [Bot Architecture](../bot/architecture/core-bot.md) - Understand the bot
- [API Documentation](../api/index.md) - Explore the API
