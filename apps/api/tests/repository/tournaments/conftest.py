"""Tournament repository test fixtures."""

import datetime as dt
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from repository.tournaments_repository import TournamentRepository


@pytest.fixture
async def repository(asyncpg_conn: asyncpg.Connection) -> TournamentRepository:
    """Provide tournament repository instance."""
    return TournamentRepository(asyncpg_conn)


@pytest.fixture
async def create_test_category(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test tournament categories.

    Returns a function that creates a category with sensible defaults.

    Usage:
        category_id = await create_test_category()
        category_id = await create_test_category(name="Hard Category", difficulties=["Hard"])
    """

    async def _create(**overrides: Any) -> int:
        # NOTE: cycle_frequency was dropped from tournaments.categories by
        # migration 0024 (global cadence now lives on tournaments.config, D-02).
        # The fixture no longer accepts/inserts it; tests that previously passed
        # cycle_frequency are stale against the edition model.
        data: dict[str, Any] = {
            "name": f"Cat-{uuid4().hex[:6]}",
            "difficulties": ["Medium"],
            "participation_xp": 100,
            "placement_xp": "[]",
            "streak_xp": "[]",
            "champion_role_id": None,
            "is_active": True,
        }
        # Drop any stale cycle_frequency override silently (column no longer exists).
        overrides.pop("cycle_frequency", None)
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            category_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.categories (
                    name, difficulties, participation_xp,
                    placement_xp, streak_xp, champion_role_id, is_active
                )
                VALUES ($1, $2::text[], $3, $4::jsonb, $5::jsonb, $6, $7)
                RETURNING id
                """,
                data["name"],
                data["difficulties"],
                data["participation_xp"],
                data["placement_xp"],
                data["streak_xp"],
                data["champion_role_id"],
                data["is_active"],
            )
        return category_id

    return _create


@pytest.fixture
async def set_global_config(asyncpg_pool: asyncpg.Pool):
    """Set global tournament config columns (cadence/anchor/pause/debug) on the singleton.

    Migration 0024 moved cadence/anchor/transitions_paused/debug_cycle_seconds onto
    tournaments.config (id = 1). This helper updates only the keys provided.

    Usage:
        await set_global_config(cadence="weekly", anchor_weekday=1)
        await set_global_config(transitions_paused=True)
        await set_global_config(debug_cycle_seconds=30)
    """

    _ALLOWED = {
        "cadence",
        "anchor_weekday",
        "anchor_time",
        "anchor_tz",
        "transitions_paused",
        "debug_cycle_seconds",
    }

    async def _set(**fields: Any) -> None:
        if not fields:
            return
        bad = set(fields) - _ALLOWED
        if bad:
            raise ValueError(f"unknown config fields: {sorted(bad)}")
        set_clauses = []
        values = []
        for idx, (field, value) in enumerate(fields.items(), start=1):
            set_clauses.append(f"{field} = ${idx}")
            values.append(value)
        query = f"UPDATE tournaments.config SET {', '.join(set_clauses)} WHERE id = 1"
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(query, *values)

    return _set


@pytest.fixture
async def create_test_edition(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating tournament editions (the timing-owning parent, D-05).

    started_at/ends_at are stored EXACT grid timestamps (never now()).

    Usage:
        edition_id = await create_test_edition(started_at, ends_at)
        edition_id = await create_test_edition(started_at, ends_at, status="completed")
    """

    async def _create(started_at: dt.datetime, ends_at: dt.datetime, **overrides: Any) -> int:
        status = overrides.get("status", "active")
        async with asyncpg_pool.acquire() as conn:
            edition_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.editions (started_at, ends_at, status)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                started_at,
                ends_at,
                status,
            )
        return edition_id

    return _create


@pytest.fixture
async def create_test_child_cycle(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating a child cycle linked to an edition (D-01/D-05).

    Mirrors create_test_cycle but binds edition_id so the cycle participates in the
    single-edition timing model.

    Usage:
        cycle_id = await create_test_child_cycle(edition_id, category_id, map_id)
        cycle_id = await create_test_child_cycle(edition_id, category_id, map_id, status="active")
    """

    async def _create(edition_id: int, category_id: int, map_id: int, **overrides: Any) -> int:
        data: dict[str, Any] = {
            "status": "active",
            "started_at": None,
            "ended_at": None,
        }
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            cycle_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles
                    (edition_id, category_id, map_id, status, started_at, ended_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                edition_id,
                category_id,
                map_id,
                data["status"],
                data["started_at"],
                data["ended_at"],
            )
        return cycle_id

    return _create


@pytest.fixture
async def advance_past_ends_at(asyncpg_pool: asyncpg.Pool):
    """Push an edition's ends_at into the past so the next cron tick treats it as due.

    This proves D-08 (drift immunity) WITHOUT real time passing: it shifts both
    started_at and ends_at back by the given delta, preserving the exact period so
    next.started_at == prev.ends_at can be asserted after a rollover.

    Usage:
        await advance_past_ends_at(edition_id)                       # 1 minute past
        await advance_past_ends_at(edition_id, seconds=3600)          # 1 hour past boundary
    """

    async def _advance(edition_id: int, seconds: int = 60) -> dt.datetime:
        async with asyncpg_pool.acquire() as conn:
            # Single atomic UPDATE: place ends_at exactly `seconds` before now()
            # and anchor started_at relative to the SAME now() so the original
            # period (ends_at - started_at) is preserved exactly. In an UPDATE
            # every SET expression reads the PRE-update row, so `(ends_at -
            # started_at)` is the original window length regardless of column
            # write order. This removes the prior read-in-between race (a
            # concurrent xdist transaction could mutate the row between the two
            # statements and make the second shift compute a stale delta).
            new_ends_at: dt.datetime = await conn.fetchval(
                """
                UPDATE tournaments.editions
                SET started_at = now() - make_interval(secs => $2) - (ends_at - started_at),
                    ends_at    = now() - make_interval(secs => $2)
                WHERE id = $1
                RETURNING ends_at
                """,
                edition_id,
                seconds,
            )
        return new_ends_at

    return _advance


@pytest.fixture
async def simulate_late_cron(asyncpg_pool: asyncpg.Pool):
    """Invoke tournaments.process_edition_transitions() after a simulated cron delay.

    pg_cron is absent in the test DB, so the transition fn is invoked directly
    (mirrors test_cycle_transitions.py). The "late" part is simulated by the caller
    having already pushed ends_at into the past via advance_past_ends_at: because the
    rewritten fn NEVER writes now() into edition timestamps (D-08), an arbitrarily
    late tick must still land on exact grid instants.

    Usage:
        await simulate_late_cron()
    """

    async def _run() -> None:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute("SELECT tournaments.process_edition_transitions()")

    return _run


@pytest.fixture
async def create_test_cycle(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test tournament cycles.

    Returns a function that creates a cycle with sensible defaults.

    Usage:
        cycle_id = await create_test_cycle(category_id, map_id)
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
    """

    async def _create(category_id: int, map_id: int, **overrides: Any) -> int:
        data: dict[str, Any] = {
            "status": "pending",
            "started_at": None,
            "ended_at": None,
        }
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            cycle_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at, ended_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                category_id,
                map_id,
                data["status"],
                data["started_at"],
                data["ended_at"],
            )
        return cycle_id

    return _create


@pytest.fixture
async def create_test_tournament_completion(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test tournament completions.

    Returns a function that creates a tournament completion with sensible defaults.

    Usage:
        completion_id = await create_test_tournament_completion(cycle_id, user_id, map_id)
        completion_id = await create_test_tournament_completion(cycle_id, user_id, map_id, time=15.0, verified=True)
    """

    async def _create(cycle_id: int, user_id: int, map_id: int, **overrides: Any) -> int:
        # Migration 0025 made `verified` a STORED generated column derived from
        # the new tri-state `status` (pending/verified/rejected). Inserting into
        # `verified` directly raises GeneratedAlwaysError, so the seed writes
        # `status`. For backward compatibility callers may still pass
        # `verified=True/False`; it is translated to `status` ('verified' for
        # True, 'pending' for False — a FALSE row was never an explicit rejection,
        # matching the migration's backfill rule). An explicit `status=` override
        # always wins.
        data: dict[str, Any] = {
            "time": 30.0,
            "screenshot": "https://example.com/screenshot.png",
            "video": None,
        }
        legacy_verified = overrides.pop("verified", None)
        status = overrides.pop("status", None)
        if status is None:
            status = "verified" if legacy_verified else "pending"
        # Migration 0029 made `completion` a STORED generated column derived from
        # video presence (completion = video IS NOT NULL). Inserting into it raises
        # GeneratedAlwaysError, so the seed no longer writes it. For backward
        # compatibility callers may still pass `completion=True/False`; a True with
        # no explicit video gets a default video URL so the generated column becomes
        # TRUE. An explicit `video=` override always wins.
        legacy_completion = overrides.pop("completion", None)
        data.update(overrides)
        if legacy_completion and data["video"] is None:
            data["video"] = "https://example.com/video.mp4"

        async with asyncpg_pool.acquire() as conn:
            completion_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.completions (
                    cycle_id, user_id, map_id, time, screenshot, video, status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                cycle_id,
                user_id,
                map_id,
                data["time"],
                data["screenshot"],
                data["video"],
                status,
            )
        return completion_id

    return _create
