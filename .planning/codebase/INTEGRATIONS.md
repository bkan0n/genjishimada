# External Integrations

**Analysis Date:** 2026-05-29

## APIs & External Services

**Discord API:**
- Used for: Bot interactions (slash commands, buttons, modals, embeds), guild management, OAuth2 authentication
- SDK/Client: `discord.py` (master branch from git) in `apps/bot/`
- Auth: `DISCORD_TOKEN` env var
- Gateway intents: guild_messages, guilds, integrations, dm_messages, webhooks, members, message_content, guild_reactions (`apps/bot/core/genji.py`)
- Bot class: `apps/bot/core/genji.py` `Genji(commands.Bot)`
- Extension system: `apps/bot/extensions/__init__.py` auto-discovers modules via `pkgutil.iter_modules`
- Debugging: `jishaku` extension loaded for development

**Resend (Email Delivery):**
- Used for: Transactional emails (verification, password reset)
- SDK/Client: `httpx` direct HTTP calls to `https://api.resend.com/emails`
- Auth: `RESEND_API_KEY` env var (Bearer token)
- From address: `FROM_EMAIL` env var, defaults to `noreply@notifications.genji.pk`
- Implementation: `apps/api/events/auth.py`
- Events:
  - `auth.verification.requested` - sends verification email on registration
  - `auth.verification.resend` - resends verification email
  - `auth.password_reset.requested` - sends password reset email
- Links point to `SITE_URL` (defaults to `https://genji.pk`)

**Sentry (Error Tracking & Performance):**
- Used for: Error tracking, performance monitoring, profiling, release management
- SDK/Client: `sentry-sdk[litestar]` (API), `sentry-sdk` with `AsyncioIntegration` (Bot)
- Auth: `SENTRY_DSN` env var
- Organization: `bkan0n`
- Project: `genjishimada`
- Configuration (both API and Bot):
  - `send_default_pii=True`
  - `enable_logs=True`
  - `traces_sample_rate=1.0`
  - `profile_session_sample_rate=1.0`
  - Environment-aware (`APP_ENVIRONMENT`)
  - Release tracked via `SENTRY_RELEASE` (git SHA)
- API init: `apps/api/app.py` (lines 174-183)
- Bot init: `apps/bot/main.py` (lines 71-84)
- Release reporting: CI/CD workflows use `sentry-cli` to create releases and associate commits after deploy

## Data Storage

**PostgreSQL 17:**
- Connection: `postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:5432/{POSTGRES_DB}`
- Client: asyncpg via `litestar-asyncpg` plugin (`apps/api/app.py`)
- Connection pooling: Managed by litestar-asyncpg, accessible via `state.db_pool`
- Custom codecs: `numeric` -> float, `jsonb` -> msgspec (`apps/api/app.py` `_async_pg_init`)
- Host resolution: Production uses `genjishimada-db`, dev uses `genjishimada-db-dev`, local uses `localhost:5432`
- Extensions: `pg_cron` (enabled in custom Dockerfile `infra/postgres/Dockerfile`)
- Schemas:
  - `core` - Users, maps, permissions
  - `maps` - Map metadata, ratings, statistics
  - `completions` - User completion records
  - `playtests` - Map playtesting data
  - `users` - User profiles, XP, rank cards
  - `lootbox` - Lootbox system
  - `rank_card` - Rank card customization
  - `content` - Movement techniques CMS
  - `public` - Jobs, idempotency claims, sessions, API tokens, auth users
- Migrations: `apps/api/migrations/*.sql` (sequential: 0001 through 0019)
- Bot-side access: Direct asyncpg connection (`apps/bot/extensions/api_service.py` imports asyncpg)
- Backup: Nightly via `.github/workflows/db-backup-nightly.yml` (runs `/opt/genji/scripts/backup_prod_db.sh` on VPS)
- Dev refresh: Weekly from production via `.github/workflows/db-refresh-dev-weekly.yml`

**S3-Compatible Object Storage (Cloudflare R2 / MinIO):**
- Used for: Image uploads (screenshots)
- Client: `boto3` with S3 compatibility (`apps/api/services/image_storage_service.py`)
- Production endpoint: `https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com`
- Local endpoint: MinIO at `http://localhost:9000` (via `S3_ENDPOINT_URL`)
- Bucket: `genji-parkour-images` (via `S3_BUCKET_NAME`)
- Public URL: `https://cdn.genji.pk` (via `S3_PUBLIC_URL`)
- Upload pattern: Content-addressable keys using BLAKE2b hash: `screenshots/{YYYY/MM/DD}/{hash}.{ext}`
- Supported formats: JPEG, PNG, WebP, AVIF, GIF, HEIC
- Cache headers: `public, max-age=31536000, immutable`
- Auth: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` env vars
- Region: `auto`

**Caching:**
- None (no Redis or dedicated cache layer)

## Message Queue (RabbitMQ 4)

**Architecture:** Producer-consumer pattern between API (produces) and Bot (consumes)

**API Side (Producer):**
- Implementation: `apps/api/services/base.py` `BaseService.publish_message()`
- Connection pool: max 2 connections, channel pool: max 10 channels (`apps/api/app.py` `rabbitmq_connection`)
- Protocol: AMQP via `aio_pika`
- Connection string: `amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/`
- Messages: `msgspec.json.encode()` payloads, `PERSISTENT` delivery mode
- Job tracking: Creates record in `public.jobs` table with UUID before publishing
- Test bypass: Skips publishing when `X-PYTEST-ENABLED=1` header present

**Bot Side (Consumer):**
- Implementation: `apps/bot/extensions/rabbit.py` `RabbitHandler`
- Queue registry: `apps/bot/extensions/_queue_registry.py` `@queue_consumer` decorator
- Connection pool: max 2 connections, channel pool: max 10 channels
- QoS: `prefetch_count=1` per queue
- Handler discovery: Scans all bot-attached service instances for `_queue_name` attribute at startup
- Load order: `rabbit.py` always loads last (enforced by sort in `apps/bot/extensions/__init__.py`)

**Registered Queues:**
- `api.completion.submission` - New completion submitted
- `api.completion.upvote` - Completion upvoted (no idempotency)
- `api.completion.verification.delete` - Verification deletion (no idempotency)
- `api.completion.autoverification.failed` - Auto-verification failed (no idempotency)
- `api.notification.delivery` - Notification to deliver (no idempotency)
- `api.playtest.creation` - New playtest created
- `api.playtest.vote.cast` - Playtest vote submitted (no idempotency)
- `api.playtest.vote.remove` - Playtest vote removed (no idempotency)
- `api.playtest.force_deny` - Playtest force-denied
- `api.xp.grant` - XP grant requested (no idempotency)

**Idempotency:**
- Queues in `IGNORE_IDEMPOTENCY` set (`apps/api/services/base.py` line 28) skip idempotency enforcement
- Bot claims idempotency via API call to `public.idempotency_claims` table
- On handler failure, claim is deleted to allow retry
- Messages carry `message_id` used as idempotency key

**Dead Letter Queue (DLQ) Pattern:**
- Each queue has a companion `<queue_name>.dlq`
- Failed messages rejected to DLQ via RabbitMQ `x-dead-letter-exchange` / `x-dead-letter-routing-key`
- DLQ processor runs every 60 seconds (`DLQ_PROCESS_INTERVAL` env var)
- Safety cap: 5000 messages per queue per scan (`DLQ_MAX_PER_QUEUE_TICK` env var)
- Alerts posted to Discord channel with message body preview
- Messages marked with `dlq_notified` header to prevent duplicate alerts
- Notified messages `nack`'d with requeue to stay in DLQ for manual inspection

**Job Status Tracking:**
- Jobs tracked in `public.jobs` table with UUID
- Status lifecycle: `queued` -> `processing` -> `succeeded` / `failed` / `timeout`
- API clients can poll job status via `/api/v3/jobs/{id}` endpoint

**RabbitMQ Infrastructure:**
- Production: Custom image from `rabbitmq:4-management` with plugins (`infra/rabbitmq/Dockerfile`)
  - Plugins: shovel, shovel_management, auth_backend_oauth2, management
  - OAuth2 config: `infra/rabbitmq/20-oauth2.conf`
- Local: Simpler image without OAuth2 (`infra/rabbitmq/Dockerfile.local`)
  - Plugins: shovel, shovel_management, management
- Init script: `infra/rabbitmq/rabbit-init.sh`
- Definitions: `infra/rabbitmq/definitions.json`

## Litestar Event System (In-Process)

**Location:** `apps/api/events/*.py`

**Registration:** Auto-discovered by `apps/api/events/__init__.py` (scans for `EventListener` instances)

**Current Events:**
- `auth.verification.requested` -> `send_verification_email` (`apps/api/events/auth.py`)
- `auth.verification.resend` -> `resend_verification_email` (`apps/api/events/auth.py`)
- `auth.password_reset.requested` -> `send_password_reset_email` (`apps/api/events/auth.py`)
- `completion.ocr.requested` -> `handle_ocr_verification` (`apps/api/events/completions.py`)

These are in-process async background tasks (not RabbitMQ queues).

## Authentication & Identity

**API Key Authentication:**
- Middleware: `apps/api/middleware/auth.py` `CustomAuthenticationMiddleware`
- Validates `X-API-KEY` header against `public.api_tokens` table
- Returns `AuthUser` (id, username, info) and `AuthToken` (api_key, is_superuser, scopes)
- Excluded paths: `/docs`, `/schema`, `/healthcheck`
- Routes opt out via `opt={"exclude_from_auth": True}`

**Scope-Based Authorization:**
- Guard: `apps/api/middleware/guards.py` `scope_guard` (global guard)
- Superusers bypass all scope checks
- Routes declare required scopes via `opt={"required_scopes": {"maps:read"}}`

**Email/Password Auth System:**
- Service: `apps/api/services/auth_service.py`
- Registration with email verification (via Resend API)
- Password reset flow with token-based email links
- Session management with refresh tokens
- BCrypt password hashing

**Bot-to-API Authentication:**
- Bot uses `API_KEY` env var to authenticate HTTP requests to the API
- API service client: `apps/bot/extensions/api_service.py` `APIService`

## Monitoring & Observability

**Error Tracking:**
- Sentry SDK in both API and Bot (see Sentry section above)

**Logging:**
- API: Litestar `LoggingConfig` with queue listener, `uvicorn.access` log filtered to exclude `/healthcheck` and `/api/v3/auth/` (`apps/api/app.py`)
- Bot: Discord.py logging setup with noise filters for gateway/state warnings (`apps/bot/main.py`)
- Both: Python `logging` module, INFO level (DEBUG in development for bot)
- Convention: `log = getLogger(__name__)` at module level, `%s` formatting (not f-strings)

**Health Check:**
- Endpoint: `GET /healthcheck` (opt out of auth)
- Validates PostgreSQL connectivity via `SELECT 1`
- Returns `503` with `Retry-After: 30` header on failure
- Docker health check polls this endpoint every 5s (`docker-compose.*.yml`)

## CI/CD & Deployment

**Hosting:**
- Self-hosted VPS accessed via SSH (configured as `genji-vps` in `~/.ssh/config`)
- Docker Compose orchestration on VPS
- External Docker network `genji-network` shared across services

**CI Pipeline (GitHub Actions):**
- `lint.yml` - Ruff format check + Ruff check + BasedPyright (API, Bot, SDK) on PRs
- `tests.yml` - pytest with testmon caching on `ubuntu-latest`, `uv sync --all-groups`, `pytest --testmon -n auto`
- Both reusable as `workflow_call` for gating deploy workflows

**CD Pipeline (GitHub Actions):**
- `deploy-dev.yml`:
  - Triggers: Manual dispatch OR `.deploy` comment on PR (via `github/branch-deploy@v11.0.0`)
  - SSH to VPS, set Docker context, `docker compose -f docker-compose.dev.yml up -d --build`
  - Reports Sentry release
  - Updates GitHub deployment status
- `deploy-prod.yml`:
  - Triggers: Push to `main` (gated by lint + test jobs)
  - Same pattern but uses `docker-compose.prod.yml`
  - Reports Sentry release with `sentry-cli`

**Database Operations (GitHub Actions):**
- `db-backup-nightly.yml`: Runs `/opt/genji/scripts/backup_prod_db.sh` on VPS via SSH (daily 2 AM CT)
- `db-refresh-dev-weekly.yml`: Runs `/opt/genji/scripts/refresh_dev_from_prod.sh` on VPS via SSH (Sundays)

**Documentation (GitHub Actions):**
- `docs.yml`: Builds OpenAPI spec + MkDocs site, deploys to GitHub Pages
- Triggers on changes to `docs/`, `mkdocs.yml`, or `apps/api/` (API changes may affect OpenAPI spec)

## Environment Configuration

**Required env vars (production):**
- `APP_ENVIRONMENT` - `production`
- `DISCORD_TOKEN` - Bot authentication
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - Database credentials
- `RABBITMQ_USER`, `RABBITMQ_PASS`, `RABBITMQ_HOST` - Message broker
- `RABBITMQ_ERLANG_COOKIE` - RabbitMQ cluster cookie
- `SENTRY_DSN` - Error tracking DSN
- `SENTRY_AUTH_TOKEN` - Sentry CLI authentication
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` - Cloudflare R2
- `RESEND_API_KEY` - Email delivery
- `API_KEY` - Bot-to-API authentication
- `DISCORD_GUILD_ID` - Target Discord server
- `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` - RabbitMQ OAuth2
- `IP_HASH_SECRET` - IP hashing for privacy

**Additional env vars (local overrides):**
- `S3_ENDPOINT_URL` - MinIO endpoint (e.g., `http://localhost:9000`)
- `S3_BUCKET_NAME` - Override bucket name
- `S3_PUBLIC_URL` - Override public URL for images
- `POSTGRES_HOST` - Override database host (defaults based on `APP_ENVIRONMENT`)
- `FROM_EMAIL` - Override sender email
- `SITE_URL` - Override site URL for email links

**Secrets location:**
- GitHub Actions secrets (per-environment: `development`, `production`)
- `.env.local` for local development (gitignored)
- `.env` for Docker Compose deployments

## Webhooks & Callbacks

**Incoming:**
- None detected (no webhook endpoints)

**Outgoing:**
- Discord messages sent via bot (DLQ alerts to configured channel, notifications, etc.)
- Resend API calls for transactional emails (`apps/api/events/auth.py`)
- Sentry event reporting (automatic via SDK)

---

*Integration audit: 2026-05-29*
