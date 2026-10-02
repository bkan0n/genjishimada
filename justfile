# Use a predictable shell (POSIX)

set shell := ["bash", "-uc"]

# ----------------------------
# One-time setup
# ----------------------------

# Initial setup: install everything once
setup:
    uv sync --all-groups --all-packages

# Update lockfile when dependencies change
lock:
    uv lock

# Re-sync after pulling changes or switching branches
sync:
    uv sync --all-groups --all-packages

fix:
    uv sync --all-groups --all-packages --reinstall

# ----------------------------
# API app (genjishimada-api)
# ----------------------------

# Run API (no sync needed if you already ran 'just setup')
run-api:
    cd apps/api && uv run --env-file ../../.env.local litestar run --reload --host 0.0.0.0 --debug

# Lint API
lint-api:
    -uv run ruff format apps/api
    -uv run ruff check apps/api
    -uv run basedpyright apps/api/repository apps/api/services apps/api/routes apps/api/middleware apps/api/utilities

# Full API suite; pass runner/pytest options after the recipe name
[positional-arguments]
test-api *args:
    uv run --project apps/api --group dev-api python scripts/run_api_tests.py "$@"

# Compatibility alias: the standard command already runs the full suite
[positional-arguments]
test-api-all *args:
    uv run --project apps/api --group dev-api python scripts/run_api_tests.py "$@"

# Compatibility alias for the feature-organized API suite
[positional-arguments]
test-api-v3 *args:
    uv run --project apps/api --group dev-api python scripts/run_api_tests.py "$@"

# Queue acceptance, including isolated process and database faults; requires Docker
test-queue:
    uv run --project apps/api --group dev-api python scripts/run_queue_tests.py

# Queue acceptance without process/container fault injection
test-queue-fast:
    uv run --project apps/api --group dev-api python scripts/run_queue_tests.py --fast

# Set a random password on the local queue-only login and save its URL in .env.local
queue-credentials-local:
    uv run --project apps/api python scripts/provision_local_queue.py

# ----------------------------
# Bot app (genjishimada-bot)
# ----------------------------

run-bot:
    cd apps/bot && uv run --env-file ../../.env.local python main.py

lint-bot:
    -uv run ruff format apps/bot
    -uv run ruff check apps/bot
    -uv run basedpyright apps/bot/core apps/bot/extensions apps/bot/utilities apps/bot/main.py

# ----------------------------
# SDK library (genjishimada-sdk)
# ----------------------------

lint-sdk:
    -uv run ruff format libs/sdk
    -uv run ruff check libs/sdk
    -uv run basedpyright libs/sdk

# ----------------------------
# Convenience
# ----------------------------

lint-all:
    just lint-api
    just lint-bot
    just lint-sdk

test-all:
    just test-api

ci:
    just lint-all
    just test-all

# Start local infrastructure (PostgreSQL and MinIO) in Docker
infra-up:
    docker compose -f docker-compose.local.yml up -d

# Stop and remove local infrastructure containers
infra-down:
    docker compose -f docker-compose.local.yml down

# Follow logs from local infrastructure
infra-logs:
    docker compose -f docker-compose.local.yml logs -f

# ----------------------------
# Documentation (MkDocs)
# ----------------------------

# Serve documentation locally with live reload
docs-serve:
    uv run --project docs mkdocs serve

# Build documentation site
docs-build:
    uv run --project apps/api python scripts/generate_openapi.py
    uv run --project docs mkdocs build

# Deploy documentation to GitHub Pages
docs-deploy:
    just docs-build
    uv run --project docs mkdocs gh-deploy --force
