<!-- refreshed: 2026-05-29 -->
# Architecture

**Analysis Date:** 2026-05-29

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                      External Clients                                   │
│         (Website, Admin Dashboard, Discord Users)                       │
└────────┬──────────────────────────────────────┬─────────────────────────┘
         │ HTTP (REST)                          │ Discord Gateway
         ▼                                      ▼
┌──────────────────────────┐        ┌──────────────────────────┐
│   Litestar REST API      │        │   Discord.py Bot         │
│   `apps/api/`            │        │   `apps/bot/`            │
│                          │        │                          │
│  ┌─────────────────────┐ │        │  ┌─────────────────────┐ │
│  │ Routes (Controllers)│ │        │  │ Extensions (Cogs)   │ │
│  │ `routes/v3/*.py`    │ │        │  │ `extensions/*.py`   │ │
│  └────────┬────────────┘ │        │  └────────┬────────────┘ │
│           ▼              │        │           │              │
│  ┌─────────────────────┐ │        │  ┌────────▼────────────┐ │
│  │ Services            │ │        │  │ APIService (HTTP)   │ │
│  │ `services/*.py`     │ │        │  │ `api_service.py`    │ │
│  └────────┬────────────┘ │        │  └─────────────────────┘ │
│           ▼              │        │                          │
│  ┌─────────────────────┐ │        │                          │
│  │ Repositories        │ │        │                          │
│  │ `repository/*.py`   │ │        │                          │
│  └─────────────────────┘ │        │                          │
└────────┬─────────┬───────┘        └────────┬─────────────────┘
         │         │                         │
    ┌────▼─────┐   │  RabbitMQ (async msgs)  │
    │PostgreSQL│   └────────────────┬────────┘
    │          │                    │
    └──────────┘              ┌────▼─────┐
                              │ RabbitMQ │
                              └──────────┘
```

The system is a Python monorepo with three packages managed by `uv` workspaces:

1. **API** (`apps/api/`) -- Litestar REST API serving `/api/v3/*`, the single source of truth for all data
2. **Bot** (`apps/bot/`) -- Discord.py bot consuming RabbitMQ events and calling the API over HTTP
3. **SDK** (`libs/sdk/`) -- Shared `msgspec.Struct` definitions ensuring type safety across the API-Bot boundary

## Component Responsibilities

| Component | Responsibility | Key File(s) |
|-----------|----------------|-------------|
| Litestar App | HTTP server, plugin/middleware wiring, exception handlers | `apps/api/app.py` |
| V3 Router | Auto-discovers Controller classes and mounts under `/api/v3` | `apps/api/routes/v3/__init__.py` |
| Controllers | HTTP parameter extraction, response serialization, exception-to-HTTP translation | `apps/api/routes/v3/*.py` |
| Services | Business logic, transaction orchestration, RabbitMQ publishing | `apps/api/services/*.py` |
| Repositories | Raw SQL via asyncpg, database exception translation | `apps/api/repository/*.py` |
| Domain Exceptions | Business rule violation errors per domain | `apps/api/services/exceptions/*.py` |
| Repository Exceptions | Structured constraint violation errors | `apps/api/repository/exceptions.py` |
| Auth Middleware | API key validation against `public.api_tokens` | `apps/api/middleware/auth.py` |
| Scope Guard | Per-endpoint scope checking (global guard) | `apps/api/middleware/guards.py` |
| Event Listeners | In-process async background tasks (email, etc.) | `apps/api/events/*.py` |
| Bot Core | discord.py `commands.Bot` subclass, extension loading | `apps/bot/core/genji.py` |
| Bot Extensions | Feature modules (slash commands, queue consumers, UI) | `apps/bot/extensions/*.py` |
| Queue Registry | `@queue_consumer` decorator for typed RabbitMQ handlers | `apps/bot/extensions/_queue_registry.py` |
| RabbitHandler | Connection pooling, queue declaration, DLQ processing | `apps/bot/extensions/rabbit.py` |
| APIService | HTTP client wrapper for bot-to-API calls | `apps/bot/extensions/api_service.py` |
| BaseHandler | Abstract base for bot services needing guild/channel refs | `apps/bot/utilities/base.py` |
| SDK Models | msgspec Struct definitions shared across API and Bot | `libs/sdk/src/genjishimada_sdk/*.py` |

## Pattern Overview

**Overall:** Three-layer Controller-Service-Repository (CSR) API with asynchronous inter-service communication via RabbitMQ.

**Key Characteristics:**
- No ORM -- all database access uses raw SQL with asyncpg positional parameters (`$1`, `$2`, ...)
- Litestar dependency injection wires controllers to services and repositories at runtime
- Domain-driven exception hierarchy translates DB errors into business errors into HTTP errors
- Bot is a consumer-only design pattern -- never writes directly to the database, always calls the API
- Shared SDK ensures the same msgspec Structs are used for serialization on both sides

## Layers

**Controllers (Route Handlers):**
- Purpose: Accept HTTP requests, validate/extract parameters, delegate to services, translate exceptions to HTTP responses
- Location: `apps/api/routes/v3/*.py`
- Contains: Litestar `Controller` subclasses with `@get`, `@post`, `@patch`, `@delete` handlers
- Depends on: Service layer, domain exceptions from `services/exceptions/`, SDK request/response structs
- Used by: External HTTP clients, Bot's `APIService`
- Pattern: Controllers declare a `dependencies` dict mapping names to `Provide(provide_*)` factory functions

```python
# apps/api/routes/v3/tags.py
class TagsController(Controller):
    tags = ["Tags"]
    path = "/tags"
    dependencies = {
        "tags_repo": Provide(provide_tags_repository),
        "tags_service": Provide(provide_tags_service),
    }

    @post(path="/search")
    async def search(self, tags_service: TagsService, data: TagsSearchFilters) -> TagsSearchResponse:
        return await tags_service.search_tags(data)
```

**Services:**
- Purpose: Business logic, transaction orchestration, RabbitMQ message publishing, cross-repository coordination
- Location: `apps/api/services/*.py`
- Contains: Service classes extending `BaseService`, domain exception raising
- Depends on: Repository layer, SDK structs, `BaseService.publish_message()`, repository exceptions
- Used by: Controller layer

```python
# apps/api/services/tags_service.py
class TagsService(BaseService):
    def __init__(self, pool: Pool, state: State, tags_repo: TagsRepository) -> None:
        super().__init__(pool, state)
        self._tags_repo = tags_repo

    async def search_tags(self, filters: TagsSearchFilters) -> TagsSearchResponse:
        return await self._tags_repo.search_tags(filters)
```

**Repositories:**
- Purpose: Data access, raw SQL queries, database exception translation
- Location: `apps/api/repository/*.py`
- Contains: Repository classes extending `BaseRepository`, raw asyncpg SQL
- Depends on: asyncpg, SDK types for query results
- Used by: Service layer

```python
# apps/api/repository/base.py
class BaseRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    def _get_connection(self, conn: Connection | None = None) -> Connection | Pool:
        return conn or self._pool
```

**Domain Exceptions:**
- Purpose: Business rule violation errors, one module per domain
- Location: `apps/api/services/exceptions/*.py`
- Contains: Exception classes inheriting from `DomainError` (defined in `apps/api/utilities/errors.py`)
- Pattern: Each domain has its own module (maps.py, completions.py, auth.py, etc.) with a base domain error and specific subclasses
- Used by: Services raise them, Controllers catch and convert to `HTTPException`

**Repository Exceptions:**
- Purpose: Structured database constraint violation errors
- Location: `apps/api/repository/exceptions.py`
- Contains: `RepositoryError` (base), `UniqueConstraintViolationError`, `ForeignKeyViolationError`, `CheckConstraintViolationError`
- Pattern: Repositories catch asyncpg exceptions and re-raise with structured context (`constraint_name`, `table`, `detail`)
- Used by: Services catch and translate into domain exceptions

## Dependency Injection Flow

Litestar's DI system wires the layers together. Each layer has a `provide_*` factory function at module bottom:

```
Controller.dependencies = {
    "maps_repo":    Provide(provide_maps_repository),     # Pool -> MapsRepository
    "maps_service": Provide(provide_maps_service),        # Pool + State + MapsRepository -> MapsService
}

# Repository provider (apps/api/repository/maps_repository.py)
async def provide_maps_repository(state: State) -> MapsRepository:
    return MapsRepository(state.db_pool)

# Service provider (apps/api/services/maps_service.py)
async def provide_maps_service(state: State, maps_repo: MapsRepository) -> MapsService:
    return MapsService(state.db_pool, state, maps_repo)
```

The DI chain resolves: `state.db_pool` -> Repository -> Service -> injected into route handler parameters.

## Data Flow

### Primary Request Path (API)

1. HTTP request arrives at Litestar (`apps/api/app.py`)
2. Auth middleware validates `X-API-KEY` header against `public.api_tokens` (`apps/api/middleware/auth.py`)
3. Scope guard checks required scopes for the endpoint (`apps/api/middleware/guards.py`)
4. Controller handler receives validated params + DI-injected service (`apps/api/routes/v3/*.py`)
5. Service executes business logic, calling repository methods (`apps/api/services/*.py`)
6. Repository runs raw SQL via asyncpg, returns dicts (`apps/api/repository/*.py`)
7. Service optionally publishes RabbitMQ message via `BaseService.publish_message()` (`apps/api/services/base.py`)
8. Controller returns SDK response struct serialized as JSON

### Async Event Processing (API -> Bot)

1. API service calls `self.publish_message(routing_key="api.completion.submission", data=event, ...)` (`apps/api/services/base.py`)
2. Job record inserted into `public.jobs` table, message published to RabbitMQ
3. `RabbitHandler` on bot side receives message (`apps/bot/extensions/rabbit.py`)
4. Handler discovered at startup via `_collect_queue_handlers()` scanning all bot extensions for `_queue_name` attribute
5. `@queue_consumer` decorator decodes msgspec body, handles idempotency, calls actual handler (`apps/bot/extensions/_queue_registry.py`)
6. `BaseHandler._wrap_job_status()` updates job status to `processing` / `succeeded` / `failed` (`apps/bot/utilities/base.py`)
7. Extension handler processes event (e.g., sends Discord embed, updates roles) (`apps/bot/extensions/*.py`)

### Bot-to-API Communication

1. Bot extension calls `self.bot.api.<method>()` (`apps/bot/extensions/api_service.py`)
2. `APIService` makes HTTP request to API with `X-API-KEY` header
3. Response decoded via msgspec into typed SDK struct

**State Management:**
- PostgreSQL is the single source of truth for all persistent state
- RabbitMQ provides at-least-once delivery for async events
- Bot maintains in-memory state for Discord guild/channel references via `BaseHandler`
- API connection pool: `state.db_pool` managed by `litestar-asyncpg` plugin
- RabbitMQ channel pool: `state.mq_channel_pool` managed in `app.py` lifespan

## Key Abstractions

**BaseService (`apps/api/services/base.py`):**
- Purpose: Base class for all API services providing RabbitMQ publishing and pool access
- Receives `Pool` and `State` via DI
- `publish_message()` creates job records, publishes to RabbitMQ, handles test mode (`X-PYTEST-ENABLED=1` header skips publishing)
- `IGNORE_IDEMPOTENCY` set defines queues that skip idempotency enforcement

**BaseRepository (`apps/api/repository/base.py`):**
- Purpose: Base class for all repositories providing connection injection
- `_get_connection(conn)` returns the injected connection (for transaction participation) or falls back to pool

**BaseHandler (`apps/bot/utilities/base.py`):**
- Purpose: Base class for bot services that need Discord guild/channel references
- Asynchronously resolves guild and channels after bot readiness
- Subclasses implement `_resolve_channels()` to cache their specific channels
- `_wrap_job_status()` wraps queue handlers to update `public.jobs` via API calls

**BaseCog (`apps/bot/utilities/base.py`):**
- Purpose: Simple base for discord.py cogs that only need a `self.bot` reference
- Used by extensions that define slash commands without queue consumption

**DomainError (`apps/api/utilities/errors.py`):**
- Purpose: Base for all domain-level business rule violations
- Carries `message` and `context` dict
- Each domain module (`services/exceptions/*.py`) defines a domain base error and specific subclasses

## Entry Points

**API Server:**
- Location: `apps/api/app.py`
- `create_app()` factory wires asyncpg plugin, router, middleware, exception handlers, Sentry, RabbitMQ lifespan
- `app = create_app()` at module level; Litestar CLI discovers it
- Run: `cd apps/api && litestar run --reload --host 0.0.0.0`

**Bot:**
- Location: `apps/bot/main.py`
- `main()` initializes Sentry, creates `aiohttp.ClientSession`, instantiates `core.Genji`, starts bot
- `Genji.setup_hook()` loads all extensions via `extensions.EXTENSIONS` then starts `RabbitHandler`
- Run: `cd apps/bot && python main.py`

**SDK:**
- Location: `libs/sdk/src/genjishimada_sdk/__init__.py`
- Pure library package, no entry point; imported by API and Bot as `genjishimada-sdk`

## Message Queue Architecture

**Queues (routing keys):**
- `api.completion.submission` -- New completion submitted (idempotent)
- `api.completion.upvote` -- Completion upvoted (non-idempotent)
- `api.completion.verification.delete` -- Verification message deleted (non-idempotent)
- `api.completion.autoverification.failed` -- Auto-verification failed (non-idempotent)
- `api.notification.delivery` -- Notification to deliver (non-idempotent)
- `api.playtest.creation` -- New playtest created (idempotent)
- `api.playtest.vote.cast` -- Playtest vote submitted (non-idempotent)
- `api.playtest.vote.remove` -- Playtest vote removed (non-idempotent)
- `api.playtest.force_deny` -- Playtest force-denied (idempotent)
- `api.xp.grant` -- XP grant requested (non-idempotent)

**Idempotency:**
- Queues NOT in `IGNORE_IDEMPOTENCY` require an `idempotency_key` parameter
- Bot-side `@queue_consumer(idempotent=True)` claims via `bot.api.claim_idempotency()` against `public.idempotency_claims` table
- On handler failure, claim is deleted to allow retry

**Dead Letter Queue (DLQ):**
- Every queue has companion `<queue_name>.dlq` declared with `x-dead-letter-exchange` and `x-dead-letter-routing-key`
- Failed messages (unhandled exceptions in `_wrap_handler`) are rejected to DLQ automatically
- DLQ processor (`_dlq_processor_loop`) runs every 60 seconds
- New DLQ messages get posted as alerts to Discord channel, then requeued with `dlq_notified` header

**Job Tracking:**
- Jobs tracked in `public.jobs` table with UUID
- Status lifecycle: `queued` -> `processing` -> `succeeded` / `failed` / `timeout`
- `BaseHandler._wrap_job_status()` wraps queue handlers to auto-update status
- API clients can poll job status via `/api/v3/jobs/{id}`

## Litestar Event System (In-Process)

- Location: `apps/api/events/*.py`
- Registration: Auto-discovered by `apps/api/events/__init__.py` scanning for `EventListener` instances
- Used for fire-and-forget background tasks within the API process
- Current events:
  - `auth.verification.requested` -- Sends verification email via Resend (`apps/api/events/auth.py`)
  - `auth.verification.resend` -- Resends verification email
  - `auth.password_reset.requested` -- Sends password reset email

## Bot Extension System

- `apps/bot/extensions/__init__.py` discovers all modules via `pkgutil.iter_modules`
- `rabbit.py` always loads last (sorted by lambda) to ensure all queue handlers are registered first
- `jishaku` loaded as a debugging extension
- Extensions loaded in `Genji.setup_hook()` during bot startup

Extensions register services on the bot instance via `setup()` functions:
```python
# apps/bot/extensions/rabbit.py
async def setup(bot: core.Genji) -> None:
    bot.rabbit = RabbitHandler(bot)
```

Bot properties (`Genji.rabbit`, `Genji.api`, `Genji.completions`, etc.) provide typed access to these services.

**Queue consumer pattern:**
```python
# apps/bot/extensions/xp.py
from extensions._queue_registry import queue_consumer

class XPHandler(BaseHandler):
    @queue_consumer("api.xp.grant", struct_type=XpGrantEvent, idempotent=False)
    async def handle_xp_grant(self, event: XpGrantEvent, message: AbstractIncomingMessage) -> None:
        # Handler logic here
```

## Authentication & Authorization

**Auth Middleware (`apps/api/middleware/auth.py`):**
- Validates `X-API-KEY` header against `public.api_tokens` table joined with `public.auth_users`
- Returns `AuthUser` (id, username, info) and `AuthToken` (api_key, is_superuser, scopes)
- Routes opt out via `opt={"exclude_from_auth": True}`
- Excluded paths: `/docs`, `/schema`, `/healthcheck`

**Scope Guard (`apps/api/middleware/guards.py`):**
- Global guard applied to all routes
- Superusers bypass all scope checks
- Routes declare required scopes via `opt={"required_scopes": {"maps:read"}}`
- Guard checks token scopes against required scopes; raises `NotAuthorizedException` on mismatch

**Full Auth System (`apps/api/services/auth_service.py`):**
- Email/password registration with verification (via Resend API)
- Password reset flow with token-based email links
- Session management with refresh tokens
- BCrypt password hashing (`apps/api/repository/auth_repository.py`)

## Architectural Constraints

- **No ORM:** All database access uses raw SQL via asyncpg. Do not introduce an ORM.
- **Single writer:** Only the API writes to PostgreSQL. The bot never writes directly -- it calls the API via HTTP.
- **Extension load order:** All bot extensions must load before `rabbit.py`. The `EXTENSIONS` list in `apps/bot/extensions/__init__.py` enforces this via sort.
- **Global state:** `state.db_pool` (asyncpg pool) and `state.mq_channel_pool` (RabbitMQ channel pool) are module-level singletons on the Litestar app state.
- **Circular imports:** Avoided via `TYPE_CHECKING` guards. Services reference other services via forward references or TYPE_CHECKING imports.
- **Threading model:** Single-threaded asyncio event loop for both API and Bot.

## Anti-Patterns

### Using the `handle_db_exceptions` Decorator for New Code

**What happens:** The legacy `handle_db_exceptions` decorator in `apps/api/utilities/errors.py` catches asyncpg constraint violations directly in route handlers, bypassing the service/repository exception hierarchy.
**Why it's wrong:** It conflates HTTP concerns with database concerns and skips the three-tier exception translation pattern.
**Do this instead:** Catch asyncpg exceptions in repositories, raise as `RepositoryError` subclasses, translate to domain exceptions in services, and convert to `HTTPException` in controllers. See `apps/api/services/exceptions/maps.py` for the correct pattern.

### Bot Writing Directly to Database

**What happens:** Bot extensions sometimes have direct asyncpg imports or database access.
**Why it's wrong:** The API is the single source of truth; bypassing it creates data consistency risks.
**Do this instead:** Always use `self.bot.api.<method>()` from `apps/bot/extensions/api_service.py` to go through the API.

## Error Handling

**Strategy:** Three-tier exception translation:

```text
asyncpg.UniqueViolationError  (database layer)
    ↓  caught in repository
UniqueConstraintViolationError  (apps/api/repository/exceptions.py)
    ↓  caught in service
MapCodeExistsError  (apps/api/services/exceptions/maps.py)
    ↓  caught in controller
HTTPException(status_code=409, detail="Provided code already exists: ABCDE")
```

**Repository -> Service translation pattern:**
```python
# In a service method
try:
    result = await self._maps_repo.create_core_map(data, conn=conn)
except UniqueConstraintViolationError as e:
    if "maps_code_key" in e.constraint_name:
        raise MapCodeExistsError(data.code) from e
    raise
```

**Service -> Controller translation pattern:**
```python
# In a controller handler
try:
    return await maps_service.create_map(data, request.headers, ...)
except MapCodeExistsError as e:
    raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
except CreatorNotFoundError as e:
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
```

**Global exception handlers** (`apps/api/app.py`):
- `default_exception_handler` -- Catches `HTTPException` / `CustomHTTPException`, returns `{"error": detail, "extra": extra}`
- `internal_server_error_handler` -- Catches 500s, returns `{"error": str(exc)}`

## Cross-Cutting Concerns

**Logging:**
- API: Litestar `LoggingConfig` with queue listener; healthcheck and auth endpoints filtered from access log
- Bot: discord.py logging setup with noise filters for gateway/state warnings
- Both: Python `logging` module; `log = getLogger(__name__)` at module level
- Use `%s` formatting (not f-strings) in log calls

**Monitoring:**
- Sentry SDK initialized in both API (`apps/api/app.py`) and Bot (`apps/bot/main.py`)
- Full traces, profiling, and PII enabled
- Environment-aware (development/production)
- Release tracking via `SENTRY_RELEASE` env var

**Serialization:**
- msgspec used throughout for JSON encoding/decoding
- Custom asyncpg type codecs for `numeric` (-> float) and `jsonb` (-> msgspec) set in `_async_pg_init` (`apps/api/app.py`)
- All shared data models use `msgspec.Struct` with naming convention: `*Request`, `*Response`, `*Event`

**Validation:**
- Request validation via msgspec Struct type hints in SDK (automatic deserialization)
- API key validation in auth middleware
- Scope validation in guard middleware
- Business rule validation in service layer (raises domain exceptions)

**Configuration:**
- API: Environment variables loaded from `.env` / `.env.local`; `just run-api` passes `--env-file`
- Bot: TOML config files decoded via msgspec (`apps/bot/utilities/config.py`)
  - `apps/bot/configs/dev.toml` -- Development Discord guild/channel/role IDs
  - `apps/bot/configs/prod.toml` -- Production Discord guild/channel/role IDs

---

*Architecture analysis: 2026-05-29*
