# API Service

The Genji Shimada API is the primary backend service powering the Genji Parkour ecosystem.
It exposes REST endpoints under `/api/v3` for maps, users, completions, playtests, ranking, lootboxes, and more.

## What the API does

- Serves REST endpoints under `/api/v3`.
- Validates input using typed models from `genjishimada-sdk`.
- Acts as the authoritative interface to PostgreSQL.
- Publishes events to RabbitMQ (XP, playtests, completions, notifications).
- Powers the Discord bot and other internal tools.

## Technologies used

- **Litestar** for async HTTP routing
- **asyncpg** for high-performance Postgres access
- **aio-pika** + RabbitMQ for async job publishing
- **msgspec** for fast JSON serialization and request validation
- **Sentry** for error tracking
- **Docker** for local and production deployment

## Code organization (high-level)

| Area | Purpose |
|------|---------|
| `apps/api/app.py` | Creates and configures the Litestar application |
| `apps/api/routes/` | Controllers + routers for each domain feature |
| `apps/api/di/` | Dependency-injected service layer |
| `apps/api/middleware/` | API key authentication + guards |
| `apps/api/utilities/` | Shared helpers and exception wrappers |

## Dependencies on other services

- **Database (Postgres)** — persistent data store
- **RabbitMQ** — async job queue for XP, completions, rank updates, notifications
- **OCR** — used by completion submission flows
- **Bot** — consumes API events and publishes some back into the system

## Related pages

- [API Overview](../api/index.md)
- [Local Development](../api/local-development.md)
- [Architecture](../api/architecture.md)
