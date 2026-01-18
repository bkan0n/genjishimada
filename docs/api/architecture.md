# Architecture

This page explains how the API is organized and why certain patterns were chosen.

## Entry point (`apps/api/app.py`)

The API is assembled in a single entry point:

- **RabbitMQ connection pools** are created during lifespan startup and stored in app state.
- **PostgreSQL** is configured with `litestar_asyncpg.AsyncpgPlugin` for pooled connections.
- **OpenAPI** metadata is configured and served at `/docs`.
- **Routing** mounts a router at `/api/v3` using `route_handlers` discovered from `apps/api/routes`.
- **Health check** is available at `/healthcheck`.

## Dynamic route loading (`apps/api/routes/__init__.py`)

Routes are discovered dynamically:

- Modules under `apps/api/routes/` are imported automatically.
- Any `litestar.Router` instance or `litestar.Controller` subclass is registered.

This keeps the entry point small and makes it easy to add new route modules.

## Controllers and dependency injection

Controllers focus on HTTP concerns. Domain logic lives in DI services under `apps/api/di/`.

Typical flow:

1. Controller method parses input and validates types.
2. It calls a DI service (e.g., `MapService`, `CompletionService`).
3. Services perform DB work and publish events.
4. The controller returns SDK response models.

## Message publishing

Services inherit from `BaseService`, which provides:

- Access to the `asyncpg` connection
- A `publish_message` helper that inserts a job row and publishes to RabbitMQ
- Optional idempotency tracking for queue messages

Queues follow the pattern: `api.<domain>.<action>`.

## Authentication and guards

- `CustomAuthenticationMiddleware` requires `X-API-KEY` on requests.
- `scope_guard` enforces route-level scopes via `opt={"required_scopes": {...}}`.
- Routes can opt out with `opt={"exclude_from_auth": True}`.

## SDK integration

The API uses models from `libs/sdk` (`genjishimada_sdk`) for request and response types, keeping shared schemas consistent across API, bot, and clients.

## Next Steps

- [Local Development](local-development.md) - Run the API locally
- [Authentication](authentication.md) - API keys and scopes
