# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Genji Shimada is a Discord bot and REST API for the Genji Parkour community. The project is a monorepo built with Python
3.13+, using `uv` for package management.

**Three main components:**

- `apps/api` - Litestar-based REST API with AsyncPG and RabbitMQ
- `apps/bot` - Discord.py bot with command/event handling
- `libs/sdk` - Shared msgspec data models and types

## Development Commands

This project uses `just` as a task runner. All commands should be run f@masrom the repository root.

### Initial Setup

```bash
just setup      # Install all dependencies (run once)
just sync       # Re-sync after pulling changes or switching branches
```

### Running Services

```bash
just run-api    # Start API server (http://localhost:8000)
just run-bot    # Start Discord bot
```

### Linting & Type Checking

```bash
just lint-api   # Format, lint, and type-check API
just lint-bot   # Format, lint, and type-check bot
just lint-sdk   # Format, lint, and type-check SDK
just lint-all   # Run all linters
```

### Testing

```bash
just test-api   # Run API tests with pytest (parallel, 8 workers)
just test-all   # Run all tests
just ci         # Run full CI suite (lint + test)
```

### Docker Compose

```bash
docker compose -f docker-compose.dev.yml up    # Start dev environment
docker compose -f docker-compose.prod.yml up   # Start production environment
```

Services in Docker:

- **genjishimada-api-dev** - API server (port exposed via healthcheck)
- **genjishimada-bot-dev** - Discord bot
- **genjishimada-db-dev** - PostgreSQL 17 (port 127.0.0.1:65432)
- **genjishimada-rabbitmq-dev** - RabbitMQ message broker

## Architecture

### Dependency Injection Pattern (API)

The API uses a "DI module" pattern where business logic is separated from HTTP routing:

- **`apps/api/di/*.py`** - DI modules contain business logic, database queries, and message publishing
- **`apps/api/routes/*.py`** - Route handlers are thin wrappers that call DI functions

**Example flow:**

1. Route handler receives HTTP request
2. Extracts/validates parameters
3. Calls DI function with database connection and parameters
4. DI function performs business logic and returns response
5. Route handler serializes and returns HTTP response

**Key DI modules:**

- `di/auth.py` - Authentication, session management, API keys
- `di/maps.py` - Map CRUD, search, ratings
- `di/completions.py` - User completion tracking
- `di/notifications.py` - Notification delivery system
- `di/base.py` - BaseService class with RabbitMQ publishing helpers

### Message Queue Architecture

The API and bot communicate asynchronously via RabbitMQ using a producer-consumer pattern:

**API Side (Producer):**

- Uses `BaseService.publish_message()` in `apps/api/di/base.py`
- Publishes msgspec-encoded messages to queues
- Creates job status records in PostgreSQL for tracking
- Supports idempotency via `message_id` header

**Bot Side (Consumer):**

- `apps/bot/extensions/rabbit.py` - RabbitService manages connections and consumers
- `apps/bot/extensions/_queue_registry.py` - `@queue_consumer` decorator for handlers
- Handlers decode msgspec structs and process events
- Supports automatic DLQ (dead letter queue) processing with alerting

**Queue naming convention:** `api.<domain>.<action>` (e.g., `api.completion.submission`, `api.notification.delivery`)

**Idempotency:**

- Most queues require idempotency (enforced by `IGNORE_IDEMPOTENCY` set in `di/base.py`)
- Bot handlers use `@queue_consumer(idempotent=True)` to claim and track message processing
- Claims are deleted on handler failure to allow retry

**DLQ Processing:**

- Failed messages go to `<queue_name>.dlq`
- DLQ processor runs every 60 seconds
- Posts alerts to Discord channel with message details
- Marks messages with `dlq_notified` header to prevent duplicate alerts

### Database Schema

**PostgreSQL with multiple schemas:**

- `core.*` - Users, maps, permissions
- `maps.*` - Map metadata, ratings, statistics
- `completions.*` - User completion records
- `playtests.*` - Map playtesting data
- `users.*` - User profiles, XP, rank cards
- `lootbox.*` - Lootbox system
- `rank_card.*` - Rank card customization
- `public.*` - Jobs, idempotency claims, sessions

**Migrations:** Located in `apps/api/migrations/*.sql` with sequential numbering (0001, 0002, etc.)

### Shared SDK

`libs/sdk/src/genjishimada_sdk/` contains msgspec Struct definitions shared between API and bot:

- All data models use `msgspec.Struct` for fast serialization
- Modules mirror domain boundaries (maps, completions, users, etc.)
- API and bot import the same structs to ensure type safety across services

**When adding new events:**

1. Define struct in appropriate `libs/sdk/src/genjishimada_sdk/*.py` file
2. Add to SDK's `__init__.py` if it's a new module
3. Use in API DI module for publishing
4. Use in bot extension with `@queue_consumer` for consuming

### Bot Extensions

The bot uses a cog-like extension system:

- **`apps/bot/core/genji.py`** - Main bot class
- **`apps/bot/extensions/*.py`** - Feature modules loaded on startup
- Extensions can define queue consumers using `@queue_consumer` decorator
- `api_service.py` - HTTP client wrapper for calling the API
- `rabbit.py` - RabbitMQ service and queue management

**Queue consumer pattern:**

```python
from extensions._queue_registry import queue_consumer
from genjishimada_sdk.completions import CompletionCreatedEvent


@queue_consumer("api.completion.submission", struct_type=CompletionCreatedEvent, idempotent=True)
async def handle_completion(self, event: CompletionCreatedEvent, message: AbstractIncomingMessage) -> None:
# Handler logic here
```

### Authentication & Middleware

**API authentication:**

- `apps/api/middleware/auth.py` - CustomAuthenticationMiddleware
- Supports API keys, session tokens, and Discord OAuth2
- Routes can opt out with `opt={"exclude_from_auth": True}`
- Scopes enforced by `middleware/guards.py` scope_guard

**Auth flow:**

1. Middleware extracts credentials from headers
2. Validates against database (sessions, API keys)
3. Attaches user/scope to request context
4. Guard checks required scopes for endpoint

## Coding Standards

**Linting:** Configured in root `pyproject.toml` with Ruff and BasedPyright

- Line length: 120 characters
- Docstring convention: Google style
- Import sorting enabled
- Strict type checking

**Type hints:** Required for all function signatures (enforced by ANN rules)

**Database access:** Always use dependency-injected `conn: Connection` parameter

**Error handling:**

- Use `CustomHTTPException` from `utilities/errors.py` for API errors
- Bot errors logged to Sentry with AsyncioIntegration

## Environment Variables

Required in `.env`:

- `DISCORD_TOKEN` - Bot token
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - Database credentials
- `RABBITMQ_USER`, `RABBITMQ_PASS`, `RABBITMQ_HOST` - Message broker
- `SENTRY_DSN` - Error tracking
- `APP_ENVIRONMENT` - `development` or `production`
- `API_KEY` - Bot's API key for calling the API
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` - S3-compatible storage
- `RESEND_API_KEY` - Email delivery

## Testing

**API tests:** `apps/api/tests/`

- Uses pytest with pytest-asyncio and pytest-databases
- Parallel execution with pytest-xdist (8 workers)
- Database fixtures provided by pytest-databases[postgres]

**Test database:** Automatically created and torn down per test

**Pytest headers:** Set `X-PYTEST-ENABLED=1` header to skip queue publishing in tests
