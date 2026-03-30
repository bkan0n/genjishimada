# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Genji Shimada is a Discord bot and REST API for the Genji Parkour community. The project is a monorepo built with Python
3.13+, using `uv` for package management.

**Three main components:**

- `apps/api` - Litestar-based REST API with AsyncPG and RabbitMQ
- `apps/bot` - Discord.py bot with command/event handling
- `libs/sdk` - Shared msgspec data models and types

## Local Development Setup

For local development, run infrastructure services in Docker and API/bot natively on your Mac:

### 1. Start Infrastructure Services

```bash
docker compose -f docker-compose.local.yml up -d
```

This starts PostgreSQL (port 5432), RabbitMQ (ports 5672, 15672), and MinIO (ports 9000, 9001) on localhost.

### 2. Import Database from VPS

```bash
# Import from dev environment
./scripts/import-db-from-vps.sh dev

# Or from production (be careful!)
./scripts/import-db-from-vps.sh prod
```

Requires SSH access to VPS with config entry `genji-vps` in `~/.ssh/config`.

### 3. Configure Local Environment

```bash
cp .env.local.example .env.local
# Edit .env.local with your local settings (Discord token, etc.)
```

The `just run-api` and `just run-bot` commands automatically use `.env.local`.

### 4. Create MinIO Bucket (First Time Only)

```bash
mc alias set local http://localhost:9000 genji local_dev_password
mc mb local/genji-parkour-images
```

### 5. Run API and Bot

```bash
# Terminal 1: Run API
just run-api

# Terminal 2: Run Bot
just run-bot
```

### 6. Access Services

- API: http://localhost:8000
- API Docs: http://localhost:8000/schema
- RabbitMQ Management: http://localhost:15672 (user: genji, pass: local_dev_password)
- MinIO Console: http://localhost:9001 (user: genji, pass: local_dev_password)

### 7. Stop Infrastructure

```bash
docker compose -f docker-compose.local.yml down
```

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

- `apps/bot/extensions/rabbit.py` - RabbitHandler manages connections and consumers
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

### Database Exception Handling

Use explicit try/except blocks only where specific error handling is needed. Not all database operations require exception handling - only add it when you need to catch and transform specific errors into user-friendly responses.

**When to add exception handling:**

- When a foreign key violation should return a specific user-friendly error
- When a unique constraint violation needs a custom message
- When you need to provide context about what failed and why

**When to let exceptions propagate:**

- For unexpected database errors (let the global error handler manage them)
- When the default error message is sufficient
- For read operations that should fail if data is missing

**Example pattern:**

```python
from repository.exceptions import ForeignKeyViolationError
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_404_NOT_FOUND


class MyService(BaseService):
    async def create_something(self, user_id: int, resource_id: int) -> Result:
        """Create something with explicit error handling.

        Raises:
            HTTPException: 404 if user or resource not found.
        """
        try:
            result = await self.repository.create(user_id, resource_id)
            return result
        except ForeignKeyViolationError as e:
            if "user_id" in e.constraint_name:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND,
                    detail="User does not exist",
                ) from e
            if "resource_id" in e.constraint_name:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND,
                    detail="Resource does not exist",
                ) from e
            raise
```

**Key principles:**

- Catch specific exception types from `repository.exceptions` (ForeignKeyViolationError, UniqueViolationError)
- Use `e.constraint_name` attribute to determine which constraint failed
- Raise HTTPException with appropriate status code and user-friendly message
- Use `raise` to re-raise if the error doesn't match expected constraints
- Always use `from e` to preserve the exception chain for debugging

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

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Movement Techniques API**

API routes and database schema for a movement techniques feature in the Genji Parkour ecosystem. This adds a content management system for Overwatch parkour movement techniques — categories, difficulties, techniques with tips and videos — exposed via REST endpoints for both the public website and an admin dashboard. Ported from the Project Momentum codebase, adapted to Genji's Litestar + AsyncPG + msgspec architecture.

**Core Value:** Provide a browsable, well-organized glossary of movement techniques that the community website can display, and that admins can manage via a dashboard — with the same data model and capabilities as the existing momentum implementation.

### Constraints

- **Tech stack**: Litestar + AsyncPG + msgspec — must follow Genji's existing patterns, not momentum's Flask/SQLAlchemy
- **Route prefix**: `/api/v3/content/movement-tech` — nested under content namespace
- **DB schema**: New `content` schema in PostgreSQL
- **No ORM**: Raw SQL via AsyncPG, consistent with rest of Genji codebase
- **Compatibility**: API response shapes should closely match momentum's for frontend reuse
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.13+ - All application code across API, bot, and SDK
- SQL - Database migrations and raw queries (`apps/api/migrations/*.sql`)
- TOML - Bot configuration (`apps/bot/configs/dev.toml`, `apps/bot/configs/prod.toml`)
- YAML - CI/CD workflows (`.github/workflows/*.yml`), Docker Compose files
## Runtime
- Python 3.13 (pinned in `.python-version`)
- Docker containers use `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` as builder, `debian:bookworm-slim` as runtime
- `uv` (Astral) - Workspace-aware package manager
- Lockfile: `uv.lock` (present, committed)
- Workspace members defined in root `pyproject.toml`: `apps/api`, `apps/bot`, `libs/sdk`, `docs`
## Frameworks
- Litestar `>=2.16.0` - REST API framework (`apps/api/app.py`)
- discord.py (master branch from git) - Discord bot framework (`apps/bot/core/genji.py`)
- discord-ext-menus (from git) - Paginated menu extension for discord.py
- msgspec `>=0.19.0` - High-performance struct serialization, used across all three packages for data models, JSON encoding/decoding, and TOML config parsing
- pytest `>=8.3.5` - Test runner
- pytest-asyncio `>=1.2.0` - Async test support (mode: `auto`)
- pytest-xdist `>=3.8.0` - Parallel test execution
- pytest-databases[postgres] `>=0.14.0` - Database fixtures for integration tests
- pytest-testmon `>=2.1.0` - Smart test selection (only re-runs affected tests)
- pytest-mock `>=3.15.1` - Mock utilities (root dev dependency)
- `just` - Task runner (`justfile` at repo root)
- Ruff `>=0.12.0` - Linting and formatting
- BasedPyright `>=1.29.4` - Static type checking (strict mode)
- complexipy `>=4.0.2` - Code complexity analysis
- Hatchling `>=1.27.0` - Build backend for SDK package (`libs/sdk/pyproject.toml`)
- MkDocs `>=1.6.0` with Material theme - Documentation site (`mkdocs.yml`, `docs/`)
- mkdocs-shadcn `>=0.9.7` - UI component theme
- Scalar - OpenAPI documentation renderer (in-app at `/docs`)
## Key Dependencies
- asyncpg (via litestar-asyncpg `>=0.4.0`) - PostgreSQL async driver and connection pooling (`apps/api/app.py`)
- aio-pika `>=9.5.5` - RabbitMQ async client for message publishing (`apps/api/services/base.py`)
- boto3 `>=1.40.25` - S3-compatible object storage client for Cloudflare R2 (`apps/api/services/image_storage_service.py`)
- httpx `>=0.27.0` - Async HTTP client for external API calls (Resend emails in `apps/api/events/auth.py`)
- bcrypt `>=4.0.0` - Password hashing (`apps/api/services/auth_service.py`, `apps/api/repository/auth_repository.py`)
- rapidfuzz `>=3.12.0` - Fuzzy string matching (dependency declared but not actively imported in source)
- sqlspec `>=0.38.0` - SQL utilities (`apps/api/utilities/map_search.py`)
- aiohttp `>=3.12.14` - HTTP client (used alongside httpx)
- aio-pika `>=9.5.5` - RabbitMQ async client for message consuming (`apps/bot/extensions/rabbit.py`)
- asyncpg `>=0.30.0` - PostgreSQL driver (bot-side DB access)
- jishaku `>=2.6.0` - Discord bot debugging/development extension
- truststore `>=0.10.4` - System CA certificate trust (`apps/bot/main.py`)
- aiohttp - HTTP session for bot and API calls (`apps/bot/extensions/api_service.py`)
- sentry-sdk[litestar] `>=2.35.1` - Error tracking and performance monitoring (API)
- sentry-sdk `>=2.29.1` - Error tracking (Bot)
- python-dotenv `>=1.1.1` - Environment variable loading
- asyncpg-stubs `>=0.31.1` - Type stubs for asyncpg
- types-boto3[boto3] `>=1.40.25` - Type stubs for boto3 (dev dependency)
- psycopg[binary] `>=3.3.2` - PostgreSQL adapter (dev dependency, likely for test tooling)
- httpx-sse `>=0.4.0` - Server-Sent Events support for httpx (dev/test dependency)
## Configuration
- `.env.local.example` provides template for local development
- `.env.local` loaded automatically by `just run-api` and `just run-bot` via `uv run --env-file`
- `.env` used for Docker Compose deployments
- Bot config via TOML files: `apps/bot/configs/dev.toml`, `apps/bot/configs/prod.toml` (Discord guild/channel/role IDs)
- `APP_ENVIRONMENT` - `local`, `development`, or `production`
- `DISCORD_TOKEN` - Bot authentication
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST` - Database
- `RABBITMQ_USER`, `RABBITMQ_PASS`, `RABBITMQ_HOST` - Message broker
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` - Object storage (production)
- `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `S3_PUBLIC_URL` - Object storage (local override for MinIO)
- `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `SENTRY_RELEASE` - Error tracking
- `RESEND_API_KEY`, `FROM_EMAIL` - Email delivery
- `API_KEY` - Bot-to-API authentication
- `DISCORD_GUILD_ID` - Target Discord server
- Root `pyproject.toml` - Workspace config, Ruff rules, BasedPyright settings
- `apps/api/pyproject.toml` - API-specific deps, pytest config, Ruff overrides
- `apps/bot/pyproject.toml` - Bot-specific deps, git-sourced discord.py
- `libs/sdk/pyproject.toml` - SDK deps (msgspec only), Hatchling build system
- Line length: 120
- Target: Python 3.13
- Ruff rules: E, F, W, A, PL, I, SIM, RUF, ASYNC, C4, INP, ERA, SLF, PIE, PYI, ANN, N, D
- Docstring convention: Google
- Test files excluded from linting
- BasedPyright in strict mode
- Test directories excluded from type checking
## Infrastructure Services
- Custom Docker image with `pg_cron` extension (`infra/postgres/Dockerfile`)
- Multiple schemas: `core`, `maps`, `completions`, `playtests`, `users`, `lootbox`, `rank_card`, `public`
- Sequential migration files in `apps/api/migrations/*.sql`
- Custom Docker image with management plugin (`infra/rabbitmq/Dockerfile`)
- Durable queues with dead-letter queue (DLQ) pattern
- Connection/channel pooling on both API and bot sides
- S3-compatible object storage for image uploads
- Local: MinIO container on ports 9000/9001
- Production: Cloudflare R2 with `cdn.genji.pk` public URL
## Platform Requirements
- macOS or Linux
- Docker (for PostgreSQL, RabbitMQ, MinIO)
- `uv` package manager
- `just` task runner
- Python 3.13+
- Discord bot token (for bot development)
- VPS (self-hosted, accessed via SSH as `genji-vps`)
- Docker Compose (`docker-compose.dev.yml` for dev server, `docker-compose.prod.yml` for production)
- External Docker network `genji-network`
- GitHub Actions for CI/CD
## CI/CD Pipeline
- `lint.yml` - Ruff + BasedPyright on PRs to main/dev
- `tests.yml` - pytest with testmon caching, runs on PRs and pushes to main/dev
- `deploy-dev.yml` - Deploy to dev VPS via SSH + Docker context (manual or `.deploy` PR comment)
- `deploy-prod.yml` - Deploy to production on push to main (after lint + test gates)
- `docs.yml` - MkDocs deployment to GitHub Pages
- `db-backup-nightly.yml` - Nightly production DB backup via SSH
- `db-refresh-dev-weekly.yml` - Weekly dev DB refresh from production
- Docker images built remotely on VPS via `docker compose up -d --build`
- Sentry release tracking with commit association
- Dev API at `https://dev-api.genji.pk`, production at `https://api.genji.pk`
- Documentation at `https://docs.genji.pk`
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Use `snake_case` for all Python files: `maps_service.py`, `completions_repository.py`
- Repository files: `{domain}_repository.py` (e.g., `repository/maps_repository.py`)
- Service files: `{domain}_service.py` (e.g., `services/maps_service.py`)
- Route files: `{domain}.py` under versioned directory (e.g., `routes/v3/maps.py`)
- Domain exception files: `services/exceptions/{domain}.py`
- SDK model files: `libs/sdk/src/genjishimada_sdk/{domain}.py`
- Bot extension files: `extensions/{feature}.py`
- Use `snake_case` for all functions and methods
- Repository methods: verb-first naming (`fetch_maps`, `create_core_map`, `lookup_map_id`, `check_code_exists`)
- Service methods: action-oriented (`create_map`, `update_map`, `send_to_playtest`)
- DI provider functions: `provide_{class_name}` (e.g., `provide_maps_service`, `provide_maps_repository`)
- Private helpers: prefix with underscore (`_normalize_custom_banner`, `_get_connection`)
- Use `snake_case` for all variables
- Connection pool: `self._pool` (private)
- State: `self._state` (private)
- Repository references: `self._maps_repo`, `self._completions_repo` (private)
- Logger: `log = getLogger(__name__)` at module level
- Use `PascalCase` for classes, Structs, and type aliases
- SDK structs: `{Domain}{Action}{Suffix}` (e.g., `MapCreateRequest`, `CompletionCreatedEvent`, `MapResponse`)
- Domain exceptions: `{Description}Error` (e.g., `MapNotFoundError`, `DuplicateCreatorError`)
- Repository exceptions: `{Constraint}ViolationError` (e.g., `UniqueConstraintViolationError`, `ForeignKeyViolationError`)
- Literal types: `DifficultyTop`, `DifficultyAll`, `MapCategory`, `OverwatchMap` (defined as `Literal[...]` in SDK)
- Use `UPPER_SNAKE_CASE`: `IGNORE_IDEMPOTENCY`, `DLQ_HEADER_KEY`, `BOT_USER_ID`
- Module-level constants prefixed with underscore when private: `_PREVIEW_MAX_LENGTH`, `_ASSET_BANNER_PATH`
## Code Style
- Tool: Ruff (format + lint)
- Line length: 120 characters
- Target Python version: 3.13
- Config: Root `pyproject.toml` and per-app `pyproject.toml`
- Tool: Ruff with extensive rule selection
- Type checker: BasedPyright (basic mode)
- Enabled rule categories:
- Key ignored rules:
- Test files exempt from ALL lint rules (`tests/**` in per-file-ignores)
## Import Organization
- Prefer `from __future__ import annotations` at top of file for forward reference support
- Use `from typing import TYPE_CHECKING` with `if TYPE_CHECKING:` blocks for circular dependency imports
- Group imports from same package on separate lines or multi-line with parentheses
- Use absolute imports within each app (e.g., `from repository.maps_repository import MapsRepository`)
- Use relative imports sparingly (`.base` within same package: `from .base import BaseService`)
## Docstrings
- All public functions and methods
- NOT required on: modules (`D100`), classes (`D101`), packages (`D104`), `__init__` methods (`D107`)
## Type Annotations
- All function parameters must have type annotations
- All return types must be annotated
- `*args` and `**kwargs` are exempt (`ANN002`, `ANN003` ignored)
- Union types: `str | None` (Python 3.10+ syntax, not `Optional[str]`)
- Annotated parameters: `Annotated[str | None, Parameter(description="...")]` for Litestar routes
- Connection parameters: `conn: Connection | None = None` (keyword-only via `*`)
- Async iterators: `AsyncIterator[asyncpg.Connection]` for fixture return types
- `typing.Any` used sparingly with `# noqa: ANN401` when needed
## Error Handling
## Logging
- Use `log` as the variable name (not `logger`)
- Use `%s` style formatting (not f-strings): `log.info("Processing map %s", code)`
- Use `log.exception()` for caught exceptions (auto-includes traceback)
- Use `log.debug()` for development/tracing messages
- Emoji prefixes in log messages for RabbitMQ operations: `[->]`, `[x]`, `[!]`
- Sentry SDK integration for error tracking in both API and bot
## Database Query Patterns
- Use `$1, $2, ...` positional parameters (asyncpg style)
- Multi-line SQL strings with triple quotes, indented for readability
- Use CTEs (`WITH ... AS`) for complex queries
- Repository methods accept optional `conn: Connection | None = None` parameter
- Use `self._get_connection(conn)` to get either the injected connection or fall back to pool
- Services acquire connections from pool and pass to repositories for transaction participation:
- `fetchval()` for single scalar values
- `fetchrow()` for single rows (returns `Record` or `None`)
- `fetch()` for multiple rows (returns `list[Record]`)
- Convert records to dicts: `dict(row)` or `[dict(row) for row in rows]`
## Data Serialization
- All shared data models use `msgspec.Struct`
- Request models: `*Request` suffix
- Response models: `*Response` suffix
- Event models: `*Event` suffix (for RabbitMQ messages)
- Use `msgspec.UNSET` / `UnsetType` for optional PATCH fields
## Dependency Injection
## Route Conventions
- Controllers extend `litestar.Controller`
- Use class-level `tags`, `path`, `dependencies`
- Scope-based auth via `opt={"required_scopes": {"scope:action"}}`
- Opt out of auth: `opt={"exclude_from_auth": True}`
## Bot Extension Conventions
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Three-layer API (Controller -> Service -> Repository) with Litestar DI
- Asynchronous inter-service communication via RabbitMQ (API produces, Bot consumes)
- Shared SDK library (`genjishimada_sdk`) provides type-safe msgspec structs across API and Bot
- Domain-driven exception hierarchy (repository exceptions -> service exceptions -> HTTP exceptions)
- PostgreSQL as single source of truth with raw SQL queries (no ORM)
## System Components
- Litestar-based REST API serving `/api/v3/*` endpoints
- Publishes events to RabbitMQ queues for the bot to consume
- Uses Litestar event system for in-process background tasks (email, OCR)
- Connects to PostgreSQL via asyncpg connection pool
- Discord.py bot with extension-based modular architecture
- Consumes RabbitMQ messages and executes Discord-side actions
- Calls the API over HTTP for data operations (via `APIService`)
- Manages Discord interactions (slash commands, buttons, modals, embeds)
- Shared msgspec `Struct` definitions used by both API and Bot
- Provides request/response/event types for all domains
- Ensures type safety across the API-Bot boundary
## Layers
- Purpose: HTTP request handling, parameter extraction, response serialization
- Location: `apps/api/routes/v3/*.py`
- Contains: Litestar `Controller` subclasses with route handlers
- Depends on: Service layer, Service exceptions, SDK structs
- Used by: External HTTP clients, Bot's `APIService`
- Pattern: Controllers declare `dependencies` dict mapping names to `Provide(provide_*)` functions. Route handlers receive service/repo instances via parameter injection.
```python
```
- Purpose: Business logic, transaction orchestration, RabbitMQ message publishing
- Location: `apps/api/services/*.py`
- Contains: Service classes extending `BaseService`, domain exception raising
- Depends on: Repository layer, SDK structs, `BaseService.publish_message()`
- Used by: Controller layer
```python
```
- Purpose: Data access, raw SQL queries, database exception translation
- Location: `apps/api/repository/*.py`
- Contains: Repository classes extending `BaseRepository`, raw asyncpg SQL
- Depends on: asyncpg, SDK types for query results
- Used by: Service layer
```python
```
- Purpose: Domain-specific business rule violation errors
- Location: `apps/api/services/exceptions/*.py`
- Contains: Exception classes per domain extending `DomainError`
- Pattern: Each domain has its own module (maps.py, completions.py, auth.py, etc.)
- Used by: Services raise them, Controllers catch and convert to HTTP exceptions
- Purpose: Database constraint violation errors
- Location: `apps/api/repository/exceptions.py`
- Contains: `UniqueConstraintViolationError`, `ForeignKeyViolationError`, `CheckConstraintViolationError`
- Pattern: Repositories catch asyncpg exceptions and re-raise as repository exceptions with structured context (constraint_name, table, detail)
## Dependency Injection Flow
```
```
## Data Flow
- PostgreSQL is the single source of truth for all persistent state
- RabbitMQ provides at-least-once delivery for async events
- Bot maintains in-memory state for Discord guild/channel references via `BaseHandler`
- API connection pool managed by `litestar-asyncpg` plugin via `state.db_pool`
- RabbitMQ channel pool managed by `state.mq_channel_pool`
## Message Queue Architecture
- `apps/api/services/base.py` `BaseService.publish_message()` publishes to RabbitMQ
- Creates job tracking record in `public.jobs` table
- Skips publishing when `X-PYTEST-ENABLED=1` header present
- Requires `idempotency_key` for most queues (enforced by `IGNORE_IDEMPOTENCY` set)
- `apps/bot/extensions/rabbit.py` `RabbitHandler` manages connection/channel pools
- `apps/bot/extensions/_queue_registry.py` `@queue_consumer` decorator for handler registration
- Queue handlers discovered at startup by scanning all bot-attached service instances
- Extensions loaded before `rabbit.py` (enforced by `extensions/__init__.py` sort order)
- `api.completion.submission` - New completion submitted
- `api.completion.upvote` - Completion upvoted
- `api.notification.delivery` - Notification to deliver
- `api.playtest.creation` - New playtest created
- `api.playtest.vote.cast` - Playtest vote submitted
- `api.playtest.force_deny` - Playtest force-denied
- `api.xp.grant` - XP grant requested
- `api.completion.autoverification.failed` - Auto-verification failed
- Messages carry `message_id` used as idempotency key
- Bot claims idempotency via API call to `public.idempotency_claims` table
- On handler failure, claim is deleted to allow retry
- Queues in `IGNORE_IDEMPOTENCY` set skip idempotency enforcement
- Each queue has a companion `<queue_name>.dlq`
- Failed messages (unhandled exceptions) are rejected to DLQ automatically via RabbitMQ `x-dead-letter-exchange`
- DLQ processor runs every 60 seconds, posting alerts to Discord channel
- Messages marked with `dlq_notified` header to prevent duplicate alerts
- Jobs tracked in `public.jobs` table with UUID
- Status lifecycle: `queued` -> `processing` -> `succeeded` / `failed` / `timeout`
- `BaseHandler._wrap_job_status()` wraps queue handlers to auto-update job status
- API clients can poll job status via `/api/v3/jobs/{id}` endpoint
## Litestar Event System (In-Process)
- **Location:** `apps/api/events/*.py`
- **Registration:** Auto-discovered by `events/__init__.py`
- **Current events:**
## Bot Extension System
- `apps/bot/extensions/__init__.py` discovers all modules via `pkgutil.iter_modules`
- `rabbit.py` always loads last (sorted by lambda) to ensure all queue handlers are registered first
- `jishaku` loaded as a debugging extension
- Extensions loaded in `Genji.setup_hook()` during bot startup
```python
```
## Authentication & Authorization
- `apps/api/middleware/auth.py` - `CustomAuthenticationMiddleware`
- Validates `X-API-KEY` header against `public.api_tokens` table
- Returns `AuthUser` (id, username, info) and `AuthToken` (api_key, is_superuser, scopes)
- Routes can opt out via `opt={"exclude_from_auth": True}`
- Excluded paths: `/docs`, `/schema`, `/healthcheck`
- `apps/api/middleware/guards.py` - `scope_guard` (global guard)
- Superusers bypass all scope checks
- Routes declare required scopes via `opt={"required_scopes": {"maps:read"}}`
- Guard checks token scopes against required scopes
- `apps/api/services/auth_service.py` - Full email/password auth system
- Registration with email verification (via Resend API)
- Password reset flow with token-based email links
- Session management with refresh tokens
- BCrypt password hashing
## Error Handling
- `RepositoryError` (base) with `message` and `context`
- `UniqueConstraintViolationError` - carries `constraint_name`, `table`, `detail`
- `ForeignKeyViolationError` - carries `constraint_name`, `table`, `detail`
- `CheckConstraintViolationError` - carries `constraint_name`, `table`, `detail`
- Repositories catch `asyncpg` exceptions and re-raise with structured context
- Per-domain exception modules (maps.py, completions.py, auth.py, etc.)
- All extend `DomainError` (from `apps/api/utilities/errors.py`)
- Services catch repository exceptions and raise domain-specific exceptions
- Example: `ForeignKeyViolationError` on creator -> `CreatorNotFoundError`
- Controllers catch service exceptions in try/except blocks
- Convert to `HTTPException` or `CustomHTTPException` with appropriate status codes
- Pattern: `except MapNotFoundError as e: raise HTTPException(status_code=404, detail=str(e)) from e`
- `default_exception_handler` - Catches `HTTPException` / `CustomHTTPException`, returns `{"error": detail, "extra": extra}`
- `internal_server_error_handler` - Catches 500s, returns `{"error": str(exc)}`
- `handle_db_exceptions` decorator - Directly catches asyncpg constraint violations in route handlers
- Maps constraint names to error messages via dicts
- Being superseded by the three-tier exception hierarchy
- `apps/bot/utilities/errors.py` - `on_command_error` handles Discord command errors
- Sentry integration captures unhandled exceptions
- Queue handler errors caught by `RabbitHandler._wrap_handler`, messages go to DLQ
## Cross-Cutting Concerns
- API: Litestar `LoggingConfig` with queue listener, healthcheck endpoint filtered out
- Bot: Discord.py logging setup with noise filters for gateway/state warnings
- Both: Python `logging` module, log level INFO (DEBUG in development)
- Sentry SDK initialized in both API (`apps/api/app.py`) and Bot (`apps/bot/main.py`)
- Full traces, profiling, and PII enabled
- Environment-aware (development/production)
- Release tracking via `SENTRY_RELEASE` env var
- msgspec used throughout for JSON encoding/decoding
- Custom asyncpg type codecs for `numeric` (-> float) and `jsonb` (-> msgspec)
- `apps/api/app.py` `_async_pg_init` sets up codecs on each connection
- Request validation via msgspec Struct type hints in SDK
- API key validation in auth middleware
- Scope validation in guard middleware
- Business rule validation in service layer (raises domain exceptions)
- API: Environment variables loaded from `.env` / `.env.local`
- Bot: TOML config files (`apps/bot/configs/dev.toml`, `apps/bot/configs/prod.toml`) decoded via msgspec
- Bot config provides guild ID, role IDs, and channel IDs
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
