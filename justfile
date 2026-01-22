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

# ----------------------------
# API app (genjishimada-api)
# ----------------------------

# Run API (no sync needed if you already ran 'just setup')
run-api:
    cd apps/api && uv run litestar run --reload --host 0.0.0.0 --debug

# Lint API
lint-api:
    -uv run ruff format apps/api
    -uv run ruff check apps/api
    -uv run basedpyright apps/api

# Test API (requires Docker to be running for test database)
test-api:
    PYTHONPATH=libs/sdk/src uv run --project apps/api --group dev-api --group dev pytest -n 6 apps/api -x

# ----------------------------
# Bot app (genjishimada-bot)
# ----------------------------

run-bot:
    cd apps/bot && uv run python main.py

lint-bot:
    -uv run ruff format apps/bot
    -uv run ruff check apps/bot
    -uv run basedpyright apps/bot

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
