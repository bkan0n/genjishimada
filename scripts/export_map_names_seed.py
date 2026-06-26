# ruff: noqa: INP001 — intentional standalone script, not an importable package module.
"""Standalone, on-demand export of the maps.names seed block.

Reads every row from ``maps.names`` on a live database and emits an
``INSERT INTO maps.names (name) VALUES (...) ON CONFLICT DO NOTHING;`` block to
stdout — the same shape as the committed seed in
``apps/api/migrations/0001_init.sql``. Run it manually to regenerate the
from-migrations bootstrap seed after maps have been added dynamically via the API.

D-10 constraints (deliberate, do not change):
    * Run MANUALLY / on-demand only. This script is NEVER imported by the API or
      bot, NEVER invoked from the request path, and is NOT wired into the nightly
      backup job. Nightly prod backups + the weekly dev refresh remain the PRIMARY
      recovery path for dynamically-added maps; this seed exists for
      from-migrations bootstrap parity (new env / catastrophic DR without a backup).

Dependency-light: stdlib + asyncpg (already a project dependency). No app imports.

Usage::

    uv run python scripts/export_map_names_seed.py            # uses POSTGRES_* env vars
    uv run python scripts/export_map_names_seed.py > seed.sql

Connection is configured via the same env-var names the API uses
(``POSTGRES_USER`` / ``POSTGRES_PASSWORD`` / ``POSTGRES_DB`` / ``POSTGRES_HOST``;
``POSTGRES_PORT`` optional, defaults to 5432).
"""

from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


def _build_dsn() -> str:
    """Build a Postgres DSN from the standard POSTGRES_* environment variables."""
    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _render_seed_block(names: list[str]) -> str:
    """Render the names as one idempotent INSERT ... ON CONFLICT DO NOTHING block."""
    if not names:
        return "-- maps.names is empty; nothing to export.\n"
    values = ",\n".join(f"    ('{name.replace(chr(39), chr(39) * 2)}')" for name in names)
    return f"INSERT INTO maps.names (name)\nVALUES\n{values}\nON CONFLICT DO NOTHING;\n"


async def export_seed() -> str:
    """Connect to the live DB, read all map names sorted, and return the seed block."""
    conn = await asyncpg.connect(_build_dsn())
    try:
        rows = await conn.fetch("SELECT name FROM maps.names ORDER BY name")
    finally:
        await conn.close()
    return _render_seed_block([row["name"] for row in rows])


async def _main() -> None:
    sys.stdout.write(await export_seed())


if __name__ == "__main__":
    asyncio.run(_main())
