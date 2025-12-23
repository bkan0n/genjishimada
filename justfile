# Use a predictable shell (POSIX)

set shell := ["bash", "-uc"]

# ----------------------------
# One-time setup
# ----------------------------

# Initial setup: install everything once
setup:
    uv sync --all-groups

# Update lockfile when dependencies change
lock:
    uv lock

# Re-sync after pulling changes or switching branches
sync:
    uv sync --all-groups

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

# Test API
test-api:
    uv run pytest -n 8 apps/api

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
