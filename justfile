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
    -uv run basedpyright apps/api/repository apps/api/services apps/api/routes_new apps/api/middleware apps/api/utilities

# Test API (requires Docker to be running for test database)
test-api:
    uv run pytest -n 4 apps/api -x

# Test v4 API only (requires Docker to be running for test database)
test-api-v4:
    uv run pytest -n 4 apps/api/test_v4 -x

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
