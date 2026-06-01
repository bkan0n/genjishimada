"""Integration tests for tournaments.process_edition_transitions() (D-01/05/08/12).

These invoke the rewritten grid-anchored transition function directly via
``SELECT tournaments.process_edition_transitions()`` (pg_cron is absent in the
test DB, mirroring test_cycle_transitions.py). They prove the structural fix:

  * drift          -- two consecutive rollovers under a *late* cron tick land on
                       exact grid instants (next.started_at == prev.ends_at), with
                       no now() leakage into edition timestamps (D-08).
  * single_edition -- one rollover creates exactly ONE new editions row and one
                       child cycle per active category, all sharing the edition
                       timing (D-01/D-05).
  * hiatus         -- with config.transitions_paused = TRUE, crossing the boundary
                       completes the current edition AND creates NO next edition AND
                       writes a results-only edition_rollover outbox row (D-12).

Wave 0 RED scaffold: these FAIL LOUDLY (not skip) until migration 0024 creates
tournaments.editions / process_edition_transitions / the global config columns;
the asyncpg calls raise UndefinedTable / UndefinedFunction / UndefinedColumn.
"""

import datetime as dt

import asyncpg
import pytest

pytestmark = [pytest.mark.domain_tournaments]


async def _active_editions(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tournaments.editions WHERE status = 'active' ORDER BY id"
        )
        return [dict(r) for r in rows]


async def _all_editions(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM tournaments.editions ORDER BY id")
        return [dict(r) for r in rows]


async def _edition(pool: asyncpg.Pool, edition_id: int) -> dict:
    async with pool.acquire() as conn:
        return dict(await conn.fetchrow("SELECT * FROM tournaments.editions WHERE id = $1", edition_id))


async def _child_cycles(pool: asyncpg.Pool, edition_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tournaments.cycles WHERE edition_id = $1 ORDER BY id",
            edition_id,
        )
        return [dict(r) for r in rows]


async def _rollover_rows(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM tournaments.pending_transitions
            WHERE event_type = 'edition_rollover'
            ORDER BY id
            """
        )
        return [dict(r) for r in rows]


class TestDrift:
    """drift: late cron ticks never shift the grid; next.started_at == prev.ends_at (D-08)."""

    async def test_drift_immune_under_late_cron(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_map,
        create_test_edition,
        create_test_child_cycle,
        set_global_config,
        advance_past_ends_at,
        simulate_late_cron,
    ):
        """Two consecutive rollovers under simulated-late ticks land on exact grid instants."""
        await set_global_config(cadence="weekly")
        category = await create_test_category()
        # Enough eligible maps for two pre-rolls.
        active_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")

        # Seed an active edition on an exact grid (1-week window).
        started_at = dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC)
        ends_at = dt.datetime(2026, 6, 8, 0, 0, tzinfo=dt.UTC)
        edition0 = await create_test_edition(started_at, ends_at)
        await create_test_child_cycle(edition0, category, active_map, status="active")

        # First rollover under a LATE tick (ends_at pushed well into the past).
        await advance_past_ends_at(edition0, seconds=3600)  # 1h late
        prev0 = await _edition(asyncpg_pool, edition0)
        await simulate_late_cron()

        active_after_1 = await _active_editions(asyncpg_pool)
        assert len(active_after_1) == 1
        edition1 = active_after_1[0]
        # The drift fix: next edition inherits the exact boundary, no now() leak.
        assert edition1["started_at"] == prev0["ends_at"]
        assert edition1["ends_at"] == prev0["ends_at"] + dt.timedelta(weeks=1)

        # Second rollover, also late.
        await advance_past_ends_at(edition1["id"], seconds=7200)  # 2h late
        prev1 = await _edition(asyncpg_pool, edition1["id"])
        await simulate_late_cron()

        active_after_2 = await _active_editions(asyncpg_pool)
        assert len(active_after_2) == 1
        edition2 = active_after_2[0]
        assert edition2["started_at"] == prev1["ends_at"]
        assert edition2["ends_at"] == prev1["ends_at"] + dt.timedelta(weeks=1)

        # The previous editions are completed (status flip only).
        assert (await _edition(asyncpg_pool, edition0))["status"] == "completed"
        assert (await _edition(asyncpg_pool, edition1["id"]))["status"] == "completed"


class TestSingleEdition:
    """single_edition: one rollover -> ONE edition + one child cycle per active category (D-01/D-05)."""

    async def test_one_rollover_one_edition_per_category(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_map,
        create_test_edition,
        create_test_child_cycle,
        set_global_config,
        advance_past_ends_at,
        simulate_late_cron,
    ):
        """All active categories transition together on one shared grid."""
        await set_global_config(cadence="weekly")
        cat_a = await create_test_category(difficulties=["Easy"])
        cat_b = await create_test_category(difficulties=["Hard"])
        map_a = await create_test_map(difficulty="Easy")
        map_b = await create_test_map(difficulty="Hard")
        # Pre-roll pool per category.
        await create_test_map(difficulty="Easy")
        await create_test_map(difficulty="Easy")
        await create_test_map(difficulty="Hard")
        await create_test_map(difficulty="Hard")

        started_at = dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC)
        ends_at = dt.datetime(2026, 6, 8, 0, 0, tzinfo=dt.UTC)
        edition0 = await create_test_edition(started_at, ends_at)
        await create_test_child_cycle(edition0, cat_a, map_a, status="active")
        await create_test_child_cycle(edition0, cat_b, map_b, status="active")

        editions_before = await _all_editions(asyncpg_pool)

        await advance_past_ends_at(edition0, seconds=120)
        await simulate_late_cron()

        editions_after = await _all_editions(asyncpg_pool)
        # Exactly ONE new edition was created.
        assert len(editions_after) == len(editions_before) + 1

        new_active = await _active_editions(asyncpg_pool)
        assert len(new_active) == 1
        new_edition = new_active[0]

        # One child cycle per active category, all bound to the SAME edition.
        children = await _child_cycles(asyncpg_pool, new_edition["id"])
        assert len(children) == 2
        assert {c["category_id"] for c in children} == {cat_a, cat_b}
        assert all(c["edition_id"] == new_edition["id"] for c in children)
        assert all(c["status"] == "active" for c in children)


class TestHiatus:
    """hiatus: paused at boundary -> current completes, NO next edition, results-only event (D-12)."""

    async def test_pause_completes_without_next_edition(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_map,
        create_test_edition,
        create_test_child_cycle,
        set_global_config,
        advance_past_ends_at,
        simulate_late_cron,
    ):
        """transitions_paused=TRUE finalizes the edition and suppresses the next one."""
        await set_global_config(cadence="weekly", transitions_paused=True)
        category = await create_test_category()
        active_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")

        started_at = dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC)
        ends_at = dt.datetime(2026, 6, 8, 0, 0, tzinfo=dt.UTC)
        edition0 = await create_test_edition(started_at, ends_at)
        await create_test_child_cycle(edition0, category, active_map, status="active")

        editions_before = await _all_editions(asyncpg_pool)

        await advance_past_ends_at(edition0, seconds=60)
        await simulate_late_cron()

        # Current edition is completed.
        assert (await _edition(asyncpg_pool, edition0))["status"] == "completed"
        # NO next edition created (hiatus).
        editions_after = await _all_editions(asyncpg_pool)
        assert len(editions_after) == len(editions_before)
        assert await _active_editions(asyncpg_pool) == []

        # A results-only edition_rollover outbox row exists.
        rollovers = await _rollover_rows(asyncpg_pool)
        assert len(rollovers) >= 1
        payload = rollovers[-1]["payload"]
        # Combined payload keys are byte-identical to TournamentRolloverEvent.
        assert set(payload.keys()) == {"results", "started", "edition_id"}
        assert payload["edition_id"] == edition0
        assert len(payload["results"]) == 1  # one finalized child cycle
        assert payload["started"] == []  # results-only: no new cycles started
