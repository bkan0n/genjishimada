# Codebase Structure

**Analysis Date:** 2026-05-29

## Directory Layout

```
genjishimada/
├── apps/
│   ├── api/                    # Litestar REST API
│   │   ├── app.py              # Application factory (create_app)
│   │   ├── events/             # Litestar in-process event listeners
│   │   ├── html/               # Static files (index.html, favicon)
│   │   ├── middleware/         # Auth middleware + scope guard
│   │   ├── migrations/         # Sequential SQL migration files (0001-0019)
│   │   ├── repository/         # Data access layer (raw SQL)
│   │   ├── routes/             # HTTP route handlers
│   │   │   └── v3/             # Versioned API controllers
│   │   ├── seeds/              # Test seed data (SQL)
│   │   ├── services/           # Business logic layer
│   │   │   └── exceptions/     # Domain exception classes
│   │   ├── tests/              # Pytest test suite
│   │   │   ├── conftest.py     # Fixtures (DB setup, test client)
│   │   │   ├── di/             # DI-specific tests
│   │   │   ├── integration/    # Integration tests
│   │   │   │   └── services/   # Service integration tests
│   │   │   ├── repository/     # Repository unit tests (per domain)
│   │   │   ├── routes/         # Route/controller tests
│   │   │   ├── services/       # Service unit tests
│   │   │   └── utilities/      # Utility tests
│   │   ├── utilities/          # Shared helpers (errors, map search, jobs)
│   │   └── pyproject.toml      # API-specific deps, pytest config
│   └── bot/                    # Discord.py bot
│       ├── main.py             # Bot entry point (Sentry, logging, startup)
│       ├── configs/            # Environment-specific TOML configs
│       │   ├── dev.toml        # Dev guild/channel/role IDs
│       │   └── prod.toml       # Prod guild/channel/role IDs
│       ├── core/               # Bot class definition
│       │   ├── __init__.py     # Re-exports Genji
│       │   └── genji.py        # Genji(commands.Bot) with service properties
│       ├── extensions/         # Feature modules loaded at startup
│       │   ├── __init__.py     # Auto-discovery, ensures rabbit.py loads last
│       │   ├── _queue_registry.py  # @queue_consumer decorator
│       │   ├── api_service.py  # HTTP client for API calls
│       │   ├── rabbit.py       # RabbitMQ handler (loads last)
│       │   ├── completions.py  # Completion queue consumers + slash commands
│       │   ├── playtest.py     # Playtest queue consumers + slash commands
│       │   ├── xp.py           # XP queue consumer + slash commands
│       │   ├── notifications.py # Notification delivery
│       │   ├── newsfeed.py     # Newsfeed posting
│       │   ├── moderator.py    # Map edit handling
│       │   ├── map_submission.py # Map submission flow
│       │   ├── map_search.py   # Map search commands
│       │   ├── map_editor.py   # Map editing commands
│       │   ├── change_requests.py # Change request handling
│       │   ├── events.py       # Discord event listeners
│       │   ├── housekeeping.py # Periodic maintenance tasks
│       │   ├── information_pages.py # Info page management
│       │   ├── modmail.py      # Modmail system
│       │   ├── settings.py     # Bot settings commands
│       │   ├── video_thumbnail.py  # Video thumbnail generation
│       │   └── tags/           # Tags feature (sub-extension)
│       ├── locales/            # i18n locale files
│       │   └── en-US/          # English locale
│       ├── utilities/          # Shared bot helpers
│       │   ├── base.py         # BaseCog, BaseHandler, BaseView
│       │   ├── _types.py       # Type aliases (GenjiItx)
│       │   ├── config.py       # TOML config decoder (msgspec)
│       │   ├── errors.py       # Error handlers
│       │   ├── emojis.py       # Emoji constants
│       │   ├── completions.py  # Completion display helpers
│       │   ├── maps.py         # Map display helpers
│       │   ├── change_requests.py # Change request helpers
│       │   ├── extra.py        # Misc utilities (job polling)
│       │   ├── formatter.py    # Text formatting utilities
│       │   ├── paginator.py    # Paginated views
│       │   ├── transformers.py # App command transformers
│       │   └── views/          # Reusable UI views
│       │       ├── mod_creator_view.py
│       │       ├── mod_guides_view.py
│       │       └── mod_status_view.py
│       └── pyproject.toml      # Bot-specific deps, git-sourced discord.py
├── libs/
│   └── sdk/                    # Shared data models
│       ├── src/
│       │   └── genjishimada_sdk/
│       │       ├── __init__.py     # Package exports (all domain modules)
│       │       ├── auth.py         # Auth request/response/event structs
│       │       ├── change_requests.py
│       │       ├── completions.py  # Completion structs + events
│       │       ├── difficulties.py # Difficulty type definitions + mappings
│       │       ├── helpers.py      # String sanitization utilities
│       │       ├── internal.py     # JobStatus, Claim structs
│       │       ├── logs.py         # Log entry structs
│       │       ├── lootbox.py      # Lootbox structs
│       │       ├── maps.py         # Map CRUD + playtest structs
│       │       ├── newsfeed.py     # Newsfeed event/record structs
│       │       ├── notifications.py # Notification structs
│       │       ├── rank_card.py    # Rank card customization
│       │       ├── store.py        # Store/shop structs
│       │       ├── tags.py         # Tags search/mutate structs
│       │       ├── users.py        # User/creator structs
│       │       ├── utilities.py    # Utility structs
│       │       └── xp.py          # XP grant structs + constants
│       └── pyproject.toml      # SDK deps (msgspec), Hatchling build
├── infra/
│   ├── postgres/               # Custom Postgres Docker image (pg_cron)
│   │   └── Dockerfile
│   └── rabbitmq/               # Custom RabbitMQ Docker image
│       ├── Dockerfile
│       ├── Dockerfile.local
│       ├── 20-oauth2.conf      # OAuth2 plugin config
│       ├── definitions.json    # Queue/exchange pre-definitions
│       └── rabbit-init.sh      # Initialization script
├── scripts/
│   ├── generate_openapi.py     # OpenAPI schema generation for docs
│   └── import-db-from-vps.sh   # Import database from VPS
├── ops/
│   ├── backup_prod_db.sh       # Production DB backup script
│   └── refresh_dev_from_prod.sh # Refresh dev DB from production
├── docs/                       # MkDocs documentation site
│   ├── api/                    # API documentation pages
│   ├── architecture/           # Architecture docs
│   ├── bot/                    # Bot documentation
│   │   ├── architecture/
│   │   ├── operations/
│   │   └── ux/
│   ├── contributing/           # Contribution guides
│   ├── getting-started/        # Setup guides
│   ├── operations/             # Operational docs
│   ├── plans/                  # Planning docs
│   ├── reviews/                # Review docs
│   ├── sdk/                    # SDK documentation
│   │   └── reference/          # SDK reference
│   ├── services/               # Service documentation
│   ├── stylesheets/            # Custom CSS
│   └── web/                    # Web documentation
├── backups/                    # Local DB backup storage
├── .github/
│   ├── ISSUE_TEMPLATE/         # GitHub issue templates
│   └── workflows/              # CI/CD pipelines
│       ├── lint.yml            # Ruff + BasedPyright on PRs
│       ├── tests.yml           # pytest with testmon
│       ├── deploy-dev.yml      # Deploy to dev VPS
│       ├── deploy-prod.yml     # Deploy to prod on push to main
│       ├── docs.yml            # MkDocs deployment
│       ├── db-backup-nightly.yml    # Nightly prod DB backup
│       └── db-refresh-dev-weekly.yml # Weekly dev DB refresh
├── .planning/                  # GSD workflow artifacts
│   └── codebase/               # Codebase analysis docs
├── pyproject.toml              # Root workspace config (uv, Ruff, Pyright)
├── justfile                    # Task runner commands
├── uv.lock                     # Dependency lockfile
├── .python-version             # Python 3.13 pin
├── .env.local.example          # Local env var template
├── Dockerfile.api              # API Docker build
├── Dockerfile.bot              # Bot Docker build
├── docker-compose.dev.yml      # Dev server Docker Compose
├── docker-compose.local.yml    # Local dev Docker Compose (infra only)
├── docker-compose.prod.yml     # Production Docker Compose
├── mkdocs.yml                  # MkDocs site configuration
├── CLAUDE.md                   # AI assistant project instructions
├── CONTRIBUTING.md             # Contribution guidelines
├── README.md                   # Project overview
├── SECURITY.md                 # Security policy
├── LICENSE                     # MIT License
└── CNAME                       # Custom domain for GitHub Pages
```

## Directory Purposes

**`apps/api/`:**
- Purpose: Litestar REST API serving `/api/v3/*` endpoints
- Contains: Three-layer architecture (routes, services, repository) plus middleware, events, migrations
- Key files: `app.py` (application factory), `pyproject.toml` (deps + pytest config)

**`apps/api/routes/v3/`:**
- Purpose: Versioned HTTP route handlers (controllers)
- Contains: One file per domain, each defining a `Controller` subclass
- Auto-discovered by `__init__.py` which scans for `Controller` subclasses and `Router` instances
- Key files: `maps.py` (1009 lines, largest), `content.py`, `auth.py`, `completions.py`

**`apps/api/services/`:**
- Purpose: Business logic layer orchestrating repositories and publishing events
- Contains: One service class per domain extending `BaseService`
- Key files: `base.py` (RabbitMQ publishing), `maps_service.py` (1984 lines, largest)

**`apps/api/services/exceptions/`:**
- Purpose: Domain-specific business rule violation errors
- Contains: One module per domain, each with a domain base error extending `DomainError`
- Key files: `maps.py`, `completions.py`, `auth.py`, `store.py`, `playtest.py`, `content.py`, `tags.py`
- `__init__.py` re-exports all exceptions for convenient importing

**`apps/api/repository/`:**
- Purpose: Data access layer with raw SQL
- Contains: One repository class per domain extending `BaseRepository`
- Key files: `base.py` (connection injection), `exceptions.py` (constraint violation errors), `maps_repository.py` (1711 lines)

**`apps/api/middleware/`:**
- Purpose: Request middleware for auth and authorization
- Contains: `auth.py` (API key validation, `AuthUser`/`AuthToken` structs), `guards.py` (scope checking)

**`apps/api/migrations/`:**
- Purpose: Sequential SQL migration files for PostgreSQL
- Contains: 19 migration files (`0001_init.sql` through `0019_release_map_code.sql`)
- Applied in sorted order during test setup and manually in production

**`apps/api/events/`:**
- Purpose: Litestar in-process event listeners for background tasks
- Contains: `auth.py` (email sending via Resend API)
- `__init__.py` auto-discovers `EventListener` instances

**`apps/api/utilities/`:**
- Purpose: Shared helper modules
- Contains: `errors.py` (CustomHTTPException, DomainError, handle_db_exceptions decorator), `map_search.py` (SQL builder), `jobs.py` (job polling), `shared_queries.py`

**`apps/api/tests/`:**
- Purpose: Pytest test suite for the API
- Structure: `repository/` (per-domain), `services/` (per-domain), `routes/`, `integration/services/`, `utilities/`, `di/`
- Key files: `conftest.py` (test DB setup with migrations + seeds)

**`apps/bot/core/`:**
- Purpose: Bot class definition
- Contains: `genji.py` defining `Genji(commands.Bot)` with typed service properties

**`apps/bot/extensions/`:**
- Purpose: Feature modules loaded as discord.py extensions at startup
- Contains: One file per feature, each with an `async def setup(bot)` function
- `__init__.py` auto-discovers all modules, sorts rabbit.py last
- `_queue_registry.py` provides the `@queue_consumer` decorator
- `api_service.py` is the HTTP client for bot-to-API communication (very large, ~85KB)

**`apps/bot/utilities/`:**
- Purpose: Shared bot helpers and base classes
- Contains: `base.py` (BaseCog, BaseHandler, BaseView), `config.py` (TOML decoder), `errors.py`, UI components
- `views/` subfolder contains reusable Discord UI views

**`libs/sdk/src/genjishimada_sdk/`:**
- Purpose: Shared msgspec Struct definitions used by both API and Bot
- Contains: One module per domain with `*Request`, `*Response`, and `*Event` structs
- Build: Uses Hatchling as build backend; installed as `genjishimada-sdk` package

**`infra/`:**
- Purpose: Custom Docker images for infrastructure services
- Contains: Postgres with pg_cron extension, RabbitMQ with management plugin and OAuth2

**`scripts/`:**
- Purpose: Developer utility scripts
- Contains: OpenAPI generation, VPS database import

**`ops/`:**
- Purpose: Operations scripts for production
- Contains: Database backup and refresh scripts

**`docs/`:**
- Purpose: MkDocs Material documentation site deployed to GitHub Pages
- Contains: Markdown pages organized by topic (API, bot, SDK, architecture, etc.)

## Key File Locations

**Entry Points:**
- `apps/api/app.py`: API application factory and Litestar app instance
- `apps/bot/main.py`: Bot startup (Sentry init, logging, `asyncio.run(main())`)
- `apps/bot/core/genji.py`: Bot class with `setup_hook()` for extension loading

**Configuration:**
- `pyproject.toml`: Root workspace config (uv workspace members, Ruff rules, Pyright settings)
- `apps/api/pyproject.toml`: API dependencies, pytest config (`asyncio_mode = "auto"`, `--testmon`)
- `apps/bot/pyproject.toml`: Bot dependencies (git-sourced discord.py), Ruff config
- `libs/sdk/pyproject.toml`: SDK dependencies (msgspec only), Hatchling build config
- `justfile`: Task runner commands (`run-api`, `run-bot`, `lint-*`, `test-*`)
- `.env.local.example`: Environment variable template
- `apps/bot/configs/dev.toml`, `apps/bot/configs/prod.toml`: Discord guild/channel/role IDs

**Core Logic:**
- `apps/api/services/base.py`: BaseService with RabbitMQ publishing
- `apps/api/repository/base.py`: BaseRepository with connection injection
- `apps/api/repository/exceptions.py`: Repository exception hierarchy
- `apps/api/utilities/errors.py`: DomainError, CustomHTTPException, handle_db_exceptions decorator
- `apps/bot/utilities/base.py`: BaseCog, BaseHandler, BaseView
- `apps/bot/extensions/_queue_registry.py`: @queue_consumer decorator
- `apps/bot/extensions/rabbit.py`: RabbitHandler (connection/channel pool, DLQ processor)

**Testing:**
- `apps/api/tests/conftest.py`: Test DB setup (migrations + seeds applied per session)
- `apps/api/tests/repository/`: Repository unit tests organized per domain
- `apps/api/tests/services/`: Service unit tests
- `apps/api/tests/routes/`: Route/controller tests
- `apps/api/tests/integration/services/`: Integration tests

## Naming Conventions

**Files:**
- Route files: `{domain}.py` (e.g., `routes/v3/maps.py`, `routes/v3/completions.py`)
- Service files: `{domain}_service.py` (e.g., `services/maps_service.py`)
- Repository files: `{domain}_repository.py` (e.g., `repository/maps_repository.py`)
- Domain exception files: `services/exceptions/{domain}.py` (e.g., `services/exceptions/maps.py`)
- SDK model files: `{domain}.py` (e.g., `genjishimada_sdk/maps.py`)
- Bot extension files: `{feature}.py` (e.g., `extensions/completions.py`)
- Migration files: `{NNNN}_{description}.sql` (e.g., `0018_movement_techniques.sql`)

**Directories:**
- Domain-specific test directories: `tests/repository/{domain}/` (e.g., `tests/repository/maps/`)
- Sub-extensions: `extensions/{feature}/` (e.g., `extensions/tags/`)

## Where to Add New Code

**New API Domain (e.g., "quests"):**
1. SDK models: `libs/sdk/src/genjishimada_sdk/quests.py` -- add to `__init__.py` exports
2. Repository: `apps/api/repository/quests_repository.py` -- extend `BaseRepository`, add `provide_quests_repository`
3. Service: `apps/api/services/quests_service.py` -- extend `BaseService`, add `provide_quests_service`
4. Domain exceptions: `apps/api/services/exceptions/quests.py` -- extend `DomainError`, add to `__init__.py`
5. Route controller: `apps/api/routes/v3/quests.py` -- `QuestsController(Controller)` with `dependencies` dict
6. Migration: `apps/api/migrations/NNNN_quests.sql` -- next sequential number
7. Seed data: `apps/api/seeds/NNNN-quests_seed.sql` (if needed for tests)
8. Tests: `apps/api/tests/repository/quests/`, `apps/api/tests/services/quests/`, `apps/api/tests/routes/quests/`

**New Bot Extension:**
1. Extension: `apps/bot/extensions/{feature}.py` -- define handler class and `async def setup(bot):`
2. If queue consumer: use `@queue_consumer` from `extensions/_queue_registry.py`
3. If needs guild/channel state: extend `BaseHandler` from `utilities/base.py`
4. If needs slash commands: extend `BaseCog` from `utilities/base.py`
5. If complex UI: add views to `utilities/views/` folder
6. Register on bot: set property in `setup()` function (e.g., `bot.my_service = MyHandler(bot)`)

**New RabbitMQ Queue:**
1. Define event struct in SDK: `libs/sdk/src/genjishimada_sdk/{domain}.py`
2. API side: call `self.publish_message(routing_key="api.{domain}.{action}", data=event, ...)` in service
3. Bot side: add `@queue_consumer("api.{domain}.{action}", struct_type=MyEvent)` handler in extension
4. If idempotent: pass `idempotent=True` to decorator; if not, add routing key to `IGNORE_IDEMPOTENCY` in `apps/api/services/base.py`

**New Utility / Shared Helper:**
- API utilities: `apps/api/utilities/{name}.py`
- Bot utilities: `apps/bot/utilities/{name}.py`
- Shared types/structs: `libs/sdk/src/genjishimada_sdk/{domain}.py`

**New Migration:**
- Location: `apps/api/migrations/NNNN_{description}.sql`
- Next number: `0020` (after current `0019_release_map_code.sql`)
- Applied automatically in test setup; manually in production

## Special Directories

**`apps/api/migrations/`:**
- Purpose: PostgreSQL schema migration files
- Generated: No (hand-written SQL)
- Committed: Yes
- Applied in sorted order

**`apps/api/seeds/`:**
- Purpose: Test seed data applied after migrations in test setup
- Generated: No (hand-written SQL)
- Committed: Yes

**`apps/api/html/`:**
- Purpose: Static files served at `/` (landing page)
- Contains: `index.html`, `favicon.ico`
- Committed: Yes

**`backups/`:**
- Purpose: Local database backup storage
- Generated: Yes (by `scripts/import-db-from-vps.sh`)
- Committed: Directory only (backups gitignored)

**`.planning/`:**
- Purpose: GSD workflow planning artifacts and codebase analysis
- Generated: Yes (by AI tools)
- Committed: Yes

**`infra/`:**
- Purpose: Custom Docker images for infrastructure services
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-05-29*
