# Technology Stack

**Analysis Date:** 2026-05-29

## Languages

**Primary:**
- Python 3.13+ - All application code across API, bot, and SDK (pinned in `.python-version`)
- SQL - Database migrations (`apps/api/migrations/*.sql`) and raw queries throughout repository layer

**Secondary:**
- TOML - Bot configuration (`apps/bot/configs/dev.toml`, `apps/bot/configs/prod.toml`), project metadata (`pyproject.toml`)
- YAML - CI/CD workflows (`.github/workflows/*.yml`), Docker Compose files (`docker-compose.*.yml`)

## Runtime

**Environment:**
- Python 3.13 (pinned in `.python-version`, enforced in `pyproject.toml` via `requires-python = ">=3.13"`)
- Docker containers: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` (builder), `debian:bookworm-slim` (runtime)

**Package Manager:**
- `uv` (Astral) - Workspace-aware package manager
- Lockfile: `uv.lock` (present, committed)
- Workspace members: `apps/api`, `apps/bot`, `libs/sdk`, `docs` (defined in root `pyproject.toml`)
- SDK linked as workspace dependency: `genjishimada-sdk = { workspace = true }`

## Frameworks

**Core:**
- Litestar `>=2.16.0` - REST API framework (`apps/api/app.py`)
- discord.py (master branch from git) - Discord bot framework (`apps/bot/core/genji.py`)
- discord-ext-menus (from git) - Paginated menu extension for discord.py
- msgspec `>=0.19.0` - High-performance struct serialization, shared across all three packages

**Testing:**
- pytest `>=8.3.5` - Test runner (`apps/api/pyproject.toml`)
- pytest-asyncio `>=1.2.0` - Async test support (mode: `auto`)
- pytest-xdist `>=3.8.0` - Parallel test execution (4 workers in `justfile`)
- pytest-databases[postgres] `>=0.14.0` - Database fixtures for integration tests
- pytest-testmon `>=2.1.0` - Smart test selection (only re-runs affected tests, cached in CI)
- pytest-mock `>=3.15.1` - Mock utilities (root dev dependency)

**Build/Dev:**
- `just` - Task runner (`justfile` at repo root)
- Ruff `>=0.12.0` - Linting and formatting
- BasedPyright `>=1.29.4` - Static type checking (strict mode)
- complexipy `>=4.0.2` - Code complexity analysis
- Hatchling `>=1.27.0` - Build backend for SDK package (`libs/sdk/pyproject.toml`)
- MkDocs `>=1.6.0` with Material theme - Documentation site (`mkdocs.yml`, `docs/`)
- mkdocs-shadcn `>=0.9.7` - UI component theme for docs
- Scalar - OpenAPI documentation renderer (in-app at `/docs` via `ScalarRenderPlugin`)

## Key Dependencies

**Critical:**
- asyncpg (via litestar-asyncpg `>=0.4.0`) - PostgreSQL async driver and connection pooling (`apps/api/app.py`)
- aio-pika `>=9.5.5` - RabbitMQ async client for message publishing/consuming (`apps/api/services/base.py`, `apps/bot/extensions/rabbit.py`)
- boto3 `>=1.40.25` - S3-compatible object storage client for Cloudflare R2 / MinIO (`apps/api/services/image_storage_service.py`)
- httpx `>=0.27.0` - Async HTTP client for external API calls (Resend emails in `apps/api/events/auth.py`)
- bcrypt `>=4.0.0` - Password hashing (`apps/api/services/auth_service.py`)
- sentry-sdk[litestar] `>=2.35.1` - Error tracking and performance monitoring (API side, `apps/api/app.py`)
- sentry-sdk `>=2.29.1` - Error tracking (Bot side, `apps/bot/main.py`)

**Infrastructure:**
- aiohttp `>=3.12.14` - HTTP client used by bot for API calls and Discord gateway (`apps/bot/extensions/api_service.py`)
- asyncpg `>=0.30.0` - PostgreSQL driver (bot-side DB access)
- python-dotenv `>=1.1.1` - Environment variable loading
- truststore `>=0.10.4` - System CA certificate trust (`apps/bot/main.py`)
- jishaku `>=2.6.0` - Discord bot debugging/development extension
- rapidfuzz `>=3.12.0` - Fuzzy string matching (declared dependency)
- sqlspec `>=0.38.0` - SQL utilities (`apps/api/utilities/map_search.py`)

**Dev/Type Stubs:**
- asyncpg-stubs `>=0.31.1` - Type stubs for asyncpg
- types-boto3[boto3] `>=1.40.25` - Type stubs for boto3
- psycopg[binary] `>=3.3.2` - PostgreSQL adapter (test tooling)
- httpx-sse `>=0.4.0` - Server-Sent Events support for httpx (test dependency)

## Configuration

**Environment:**
- `.env.local.example` provides template for local development
- `.env.local` loaded automatically by `just run-api` and `just run-bot` via `uv run --env-file`
- `.env` used for Docker Compose deployments
- Bot config via TOML files: `apps/bot/configs/dev.toml`, `apps/bot/configs/prod.toml` (Discord guild/channel/role IDs)
- `APP_ENVIRONMENT` controls behavior: `local`, `development`, or `production`

**Required Environment Variables:**
- `DISCORD_TOKEN` - Bot authentication
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST` - Database connection
- `RABBITMQ_USER`, `RABBITMQ_PASS`, `RABBITMQ_HOST` - Message broker
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` - Object storage (production)
- `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `S3_PUBLIC_URL` - Object storage (local override for MinIO)
- `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `SENTRY_RELEASE` - Error tracking
- `RESEND_API_KEY`, `FROM_EMAIL` - Email delivery
- `API_KEY` - Bot-to-API authentication
- `DISCORD_GUILD_ID` - Target Discord server

**Build/Lint Config:**
- Root `pyproject.toml` - Workspace config, Ruff rules, BasedPyright settings
- `apps/api/pyproject.toml` - API-specific deps, pytest config, Ruff overrides
- `apps/bot/pyproject.toml` - Bot-specific deps, git-sourced discord.py
- `libs/sdk/pyproject.toml` - SDK deps (msgspec only), Hatchling build system
- Line length: 120
- Target: Python 3.13
- Ruff rules: E, F, W, A, PL, I, SIM, RUF, ASYNC, C4, INP, ERA, SLF, PIE, PYI, ANN, N, D
- Docstring convention: Google
- Test files excluded from linting
- BasedPyright in strict mode (test directories excluded from type checking)

## Infrastructure Services

**PostgreSQL 17:**
- Custom Docker image with `pg_cron` extension (`infra/postgres/Dockerfile`)
- Multiple schemas: `core`, `maps`, `completions`, `playtests`, `users`, `lootbox`, `rank_card`, `public`, `content`
- Sequential migration files in `apps/api/migrations/*.sql` (0001 through 0019)
- Connection pooling via litestar-asyncpg plugin
- Custom type codecs: `numeric` -> float, `jsonb` -> msgspec (`apps/api/app.py` `_async_pg_init`)

**RabbitMQ 4:**
- Custom Docker image with management plugin (`infra/rabbitmq/Dockerfile`)
- Plugins: `rabbitmq_shovel`, `rabbitmq_shovel_management`, `rabbitmq_auth_backend_oauth2`, `rabbitmq_management`
- Local variant without OAuth2 (`infra/rabbitmq/Dockerfile.local`)
- Durable queues with dead-letter queue (DLQ) pattern
- Connection pool (max 2) and channel pool (max 10) on both API and bot sides
- Queue init script: `infra/rabbitmq/rabbit-init.sh`
- Definitions loaded from `infra/rabbitmq/definitions.json`

**Object Storage (S3-compatible):**
- Production: Cloudflare R2 with `cdn.genji.pk` public URL
- Local: MinIO container on ports 9000/9001
- Bucket: `genji-parkour-images`
- Used for screenshot uploads (`apps/api/services/image_storage_service.py`)

## Platform Requirements

**Development:**
- macOS or Linux
- Docker (for PostgreSQL, RabbitMQ, MinIO)
- `uv` package manager
- `just` task runner
- Python 3.13+
- Discord bot token (for bot development)

**Production:**
- Self-hosted VPS (accessed via SSH as `genji-vps`)
- Docker Compose (`docker-compose.dev.yml` for dev server, `docker-compose.prod.yml` for production)
- External Docker network `genji-network`
- GitHub Actions for CI/CD

## CI/CD Pipeline

**Workflows (`.github/workflows/`):**
- `lint.yml` - Ruff format + check + BasedPyright on PRs to main/dev
- `tests.yml` - pytest with testmon caching, runs on PRs and pushes to main/dev
- `deploy-dev.yml` - Deploy to dev VPS via SSH + Docker context (manual or `.deploy` PR comment via `github/branch-deploy@v11.0.0`)
- `deploy-prod.yml` - Deploy to production on push to main (gated by lint + test jobs)
- `docs.yml` - MkDocs deployment to GitHub Pages on changes to `docs/`, `mkdocs.yml`, or `apps/api/`
- `db-backup-nightly.yml` - Nightly production DB backup via SSH (cron `0 8 * * *` UTC / 2 AM CT)
- `db-refresh-dev-weekly.yml` - Weekly dev DB refresh from production (Sundays)

**Deployment Pattern:**
- Docker images built remotely on VPS via `docker compose up -d --build`
- Sentry release tracking with commit association after successful deploy
- Dev API: `https://dev-api.genji.pk`
- Production API: `https://api.genji.pk`
- Documentation: `https://docs.genji.pk`

---

*Stack analysis: 2026-05-29*
