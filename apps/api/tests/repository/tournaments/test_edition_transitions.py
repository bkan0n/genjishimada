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
                       moves the current edition to awaiting_results AND creates NO
                       next edition (D-12).

Phase 12.1 (D-06/D-07): the cron is now TIMING-ONLY. Crossing the boundary flips
the due edition active -> ``awaiting_results`` (NOT ``completed``), flips child
cycles -> ``finalizing`` (NOT ``completed``), creates edition N+1 grid-anchored,
and writes NO outbox row / NO leaderboard snapshot. The outbox POLLER owns
results computation + the terminal ``completed`` flip when verification drains
(see test_outbox_poller.py). These tests therefore assert the poller-owns-results
model: the cron stops at ``awaiting_results``/``finalizing`` and emits no outbox
row.
"""

import datetime as dt

import asyncpg
import pytest

pytestmark = [pytest.mark.domain_tournaments]


async def _find_chained_edition(pool: asyncpg.Pool, prev_ends_at: dt.datetime) -> dict:
    """Find the edition the rollover created by chaining off the previous ends_at.

    The session-scoped test DB is shared across sibling tests, so a global
    "active editions" query is unreliable; the drift fix means next.started_at ==
    prev.ends_at exactly, which is a stable, isolation-safe selector.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tournaments.editions WHERE started_at = $1 ORDER BY id DESC LIMIT 1",
            prev_ends_at,
        )
        assert row is not None, f"no edition chained off ends_at={prev_ends_at!r}"
        return dict(row)


async def _all_editions(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM tournaments.editions ORDER BY id")
        return [dict(r) for r in rows]


async def _edition(pool: asyncpg.Pool, edition_id: int) -> dict:
    async with pool.acquire() as conn:
        return dict(await conn.fetchrow("SELECT * FROM tournaments.editions WHERE id = $1", edition_id))


async def _roll_until_awaiting_results(pool: asyncpg.Pool, run_cron, edition_id: int, max_ticks: int = 20) -> None:
    """Invoke the timing-only transition fn until the target edition flips to awaiting_results.

    Phase 12.1 (D-06): the cron flips the due edition active -> ``awaiting_results``
    (NOT ``completed``) -- results + the terminal ``completed`` flip are owned by
    the outbox poller (D-07). The fn rolls the globally-earliest due edition per
    call; on the shared test DB sibling tests may leave other due editions, so we
    tick (bounded) until ours flips.
    """
    for _ in range(max_ticks):
        if (await _edition(pool, edition_id))["status"] == "awaiting_results":
            return
        await run_cron()
    assert (await _edition(pool, edition_id))["status"] == "awaiting_results", (
        f"edition {edition_id} not moved to awaiting_results after {max_ticks} ticks"
    )


async def _child_cycles(pool: asyncpg.Pool, edition_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tournaments.cycles WHERE edition_id = $1 ORDER BY id",
            edition_id,
        )
        return [dict(r) for r in rows]


async def _rollover_rows(pool: asyncpg.Pool, edition_id: int | None = None) -> list[dict]:
    async with pool.acquire() as conn:
        if edition_id is None:
            rows = await conn.fetch(
                """
                SELECT * FROM tournaments.pending_transitions
                WHERE event_type = 'edition_rollover'
                ORDER BY id
                """
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM tournaments.pending_transitions
                WHERE event_type = 'edition_rollover' AND edition_id = $1
                ORDER BY id
                """,
                edition_id,
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
        await set_global_config(cadence="weekly", transitions_paused=False)
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
        # The transition fn rolls the globally-earliest due edition per call; on a
        # shared test DB other tests' editions may also be due, so tick until THIS
        # edition has flipped to awaiting_results (bounded). Phase 12.1: the cron is
        # timing-only -- it stops at awaiting_results, the poller finalizes (D-06/D-07).
        await _roll_until_awaiting_results(asyncpg_pool, simulate_late_cron, edition0)

        # The drift fix: next edition inherits the exact boundary, no now() leak.
        edition1 = await _find_chained_edition(asyncpg_pool, prev0["ends_at"])
        assert edition1["started_at"] == prev0["ends_at"]
        assert edition1["ends_at"] == prev0["ends_at"] + dt.timedelta(weeks=1)

        # Second rollover, also late.
        await advance_past_ends_at(edition1["id"], seconds=7200)  # 2h late
        prev1 = await _edition(asyncpg_pool, edition1["id"])
        await _roll_until_awaiting_results(asyncpg_pool, simulate_late_cron, edition1["id"])

        edition2 = await _find_chained_edition(asyncpg_pool, prev1["ends_at"])
        assert edition2["started_at"] == prev1["ends_at"]
        assert edition2["ends_at"] == prev1["ends_at"] + dt.timedelta(weeks=1)

        # The previous editions sit at awaiting_results (timing-only flip; the
        # poller owns the terminal completed flip + results, D-06/D-07).
        assert (await _edition(asyncpg_pool, edition0))["status"] == "awaiting_results"
        assert (await _edition(asyncpg_pool, edition1["id"]))["status"] == "awaiting_results"


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
        await set_global_config(cadence="weekly", transitions_paused=False)
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

        await advance_past_ends_at(edition0, seconds=120)
        prev0 = await _edition(asyncpg_pool, edition0)
        await _roll_until_awaiting_results(asyncpg_pool, simulate_late_cron, edition0)

        # Exactly ONE next edition was created (chained off the exact boundary, D-08).
        new_edition = await _find_chained_edition(asyncpg_pool, prev0["ends_at"])
        assert new_edition["ends_at"] == prev0["ends_at"] + dt.timedelta(weeks=1)

        # Both of this test's categories got exactly one child cycle in the SAME
        # (single) new edition (D-01/D-05). Scope to this test's categories; the
        # shared test DB may carry other active categories that also pre-roll.
        children = await _child_cycles(asyncpg_pool, new_edition["id"])
        mine = [c for c in children if c["category_id"] in (cat_a, cat_b)]
        assert {c["category_id"] for c in mine} == {cat_a, cat_b}
        assert len([c for c in mine if c["category_id"] == cat_a]) == 1
        assert len([c for c in mine if c["category_id"] == cat_b]) == 1
        # All child cycles of this rollover share the one edition (single shared grid).
        assert all(c["edition_id"] == new_edition["id"] for c in mine)
        assert all(c["status"] == "active" for c in mine)


class TestHiatus:
    """hiatus: paused at boundary -> current goes awaiting_results, NO next edition, NO outbox row (D-06/D-12)."""

    async def test_pause_awaits_results_without_next_edition(
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
        """transitions_paused=TRUE moves the edition to awaiting_results and suppresses the next one."""
        await set_global_config(cadence="weekly", transitions_paused=True)
        category = await create_test_category()
        active_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")

        started_at = dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC)
        ends_at = dt.datetime(2026, 6, 8, 0, 0, tzinfo=dt.UTC)
        edition0 = await create_test_edition(started_at, ends_at)
        await create_test_child_cycle(edition0, category, active_map, status="active")

        await advance_past_ends_at(edition0, seconds=60)
        # While paused the fn never creates a next edition, so chaining off ends_at
        # would find nothing -- assert by id instead.
        await _roll_until_awaiting_results(asyncpg_pool, simulate_late_cron, edition0)

        # Phase 12.1: the timing-only cron stops at awaiting_results (the poller
        # later finalizes + publishes results, D-06/D-07). Child cycles are
        # finalizing (submissions stopped), NOT completed.
        awaiting = await _edition(asyncpg_pool, edition0)
        assert awaiting["status"] == "awaiting_results"
        # NO next edition created (hiatus): nothing chains off this edition's boundary.
        async with asyncpg_pool.acquire() as conn:
            chained = await conn.fetch(
                "SELECT id FROM tournaments.editions WHERE started_at = $1",
                awaiting["ends_at"],
            )
        assert chained == []
        # Child cycles are finalizing (the cron stops new submissions; the poller
        # flips them to completed when results publish).
        assert all(c["status"] == "finalizing" for c in await _child_cycles(asyncpg_pool, edition0))

        # The timing-only cron writes NO outbox row (D-06): results computation +
        # the edition_rollover/edition_results event are owned by the poller.
        assert await _rollover_rows(asyncpg_pool, edition0) == []
