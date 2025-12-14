# Use a predictable shell (POSIX) even if your login shell is fish
set shell := ["bash", "-uc"]

# ----------------------------
# Workspace-wide helpers
# ----------------------------

# Sync everything (runtime deps + default groups from root pyproject, if any)
sync:
    uv sync

# Regenerate lockfile (all members)
lock:
    uv lock

# ----------------------------
# API app (genjishimada-api)
# ----------------------------

# Runtime deps only for API (no dev groups)
sync-api:
    uv sync --package genjishimada-api

# API + its dev group (pytest, asyncpg-stubs, etc.) + any default groups
sync-api-dev:
    uv sync --package genjishimada-api --group dev-api

# Run API dev server with reload + debug
run-api:
    cd apps/api && uv run --package genjishimada-api litestar run --reload --host 0.0.0.0 --debug

# Lint API (format + lint) using shared dev tools
lint-api:
    uv run --package genjishimada-api --group dev-common ruff format apps/api
    uv run --package genjishimada-api --group dev-common ruff check apps/api
    uv run --package genjishimada-api --group dev-common basedpyright apps/api

# Run API tests (ensures dev deps for API are installed)
test-api:
    uv sync --package genjishimada-api --group dev-api
    uv run  --package genjishimada-api --group dev-api pytest -n 8 apps/api

# ----------------------------
# Bot app (genjishimada-bot)
# ----------------------------

# Runtime deps only for Bot
sync-bot:
    uv sync --package genjishimada-bot

# Bot + its dev deps (mkdocs, etc.)
sync-bot-dev:
    uv sync --package genjishimada-bot --group dev-bot

# Run the bot
run-bot:
    cd apps/bot && uv run --package genjishimada-bot python main.py

# Lint bot using shared dev tools
lint-bot:
    uv run --package genjishimada-bot --group dev-common ruff format apps/bot
    uv run --package genjishimada-bot --group dev-common ruff check apps/bot
    uv run --package genjishimada-bot --group dev-common basedpyright apps/bot

# ----------------------------
# SDK library (genjishimada-sdk)
# ----------------------------

# Runtime deps only for SDK
sync-sdk:
    uv sync --package genjishimada-sdk

# Shared dev tools for SDK too
sync-sdk-dev:
    uv sync --package genjishimada-sdk --group dev-common

lint-sdk:
    uv run --package genjishimada-sdk --group dev-common ruff format libs/sdk
    uv run --package genjishimada-sdk --group dev-common ruff check libs/sdk
    uv run --package genjishimada-sdk --group dev-common basedpyright libs/sdk

# ----------------------------
# Convenience combos
# ----------------------------

# Full dev setup for API + Bot + SDK
sync-all-dev:
    just sync-api-dev
    just sync-bot-dev
    just sync-sdk-dev

# Run full lint over everything
lint-all:
    just lint-api
    just lint-bot
    just lint-sdk

# Run all tests (right now only API has tests)
test-all:
    just test-api
