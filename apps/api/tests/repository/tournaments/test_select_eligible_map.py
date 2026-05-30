"""Parity tests for the tournaments.select_eligible_map() SQL helper.

The transition function (07-01) pre-rolls the next cycle in SQL via
``tournaments.select_eligible_map(category_id)``, which duplicates the Phase 5
Python selection logic (``TournamentRepository.fetch_eligible_maps`` +
``fetch_least_recently_used_map``). These tests prove the SQL helper enforces the
same eligibility set: difficulty grouping (with ``-``/``+`` normalization),
blacklist-window exclusion, pending-cycle exclusion, LRU fallback, NULL when no
maps match, and membership parity with the Python path (D-06).

The integration DB is shared session-wide, so other tests/seeds may add maps of
common difficulties. Tests therefore assert eligibility *properties* (the chosen
map matches the difficulty grouping, excluded maps are never returned, and the
SQL pick is a subset of the live Python-eligible set) rather than exact set
equality. Tests that need an exhausted pool use rare difficulty groupings that
no other test/seed populates.
"""

import datetime as dt

import asyncpg
import pytest

from repository.tournaments_repository import TournamentRepository

pytestmark = [pytest.mark.domain_tournaments]


def _days_ago(days: int) -> dt.datetime:
    return dt.datetime.now(dt.UTC) - dt.timedelta(days=days)


async def _select(pool: asyncpg.Pool, category_id: int) -> int | None:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT tournaments.select_eligible_map($1)", category_id)


async def _base_difficulty(pool: asyncpg.Pool, map_id: int) -> str:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            r"SELECT regexp_replace(difficulty, '\s*[-+]\s*$', '', '') FROM core.maps WHERE id = $1",
            map_id,
        )


async def _set_blacklist_weeks(pool: asyncpg.Pool, weeks: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tournaments.config SET blacklist_weeks = $1 WHERE id = 1", weeks)


class TestDifficultyFilter:
    """select_eligible_map only returns maps whose base difficulty is in the category."""

    async def test_select_respects_difficulties(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_map,
    ):
        """Every returned map normalizes to a base difficulty in the category grouping."""
        category = await create_test_category(difficulties=["Hard"])

        # In-grouping: "Hard +" and "Hard -" both normalize to "Hard".
        await create_test_map(difficulty="Hard +")
        await create_test_map(difficulty="Hard -")
        await create_test_map(difficulty="Hard")
        # Out of grouping (must never be selected for a "Hard" category).
        await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Easy")

        # Sample multiple times since the helper uses ORDER BY random().
        for _ in range(20):
            selected = await _select(asyncpg_pool, category)
            assert selected is not None
            assert await _base_difficulty(asyncpg_pool, selected) == "Hard"


class TestBlacklistWindow:
    """Maps used within the blacklist window are excluded."""

    async def test_select_excludes_blacklist_window(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A map used in a recent cycle is never returned."""
        await _set_blacklist_weeks(asyncpg_pool, 4)
        category = await create_test_category(difficulties=["Medium"])

        in_window_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")  # an eligible alternative

        # Used 1 week ago (well within the 4-week blacklist window).
        await create_test_cycle(category, in_window_map, status="completed", started_at=_days_ago(7))

        for _ in range(20):
            selected = await _select(asyncpg_pool, category)
            assert selected is not None
            assert selected != in_window_map


class TestPendingExclusion:
    """Maps attached to a pending cycle are excluded."""

    async def test_select_excludes_pending(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A map already in a pending cycle is never selected."""
        category = await create_test_category(difficulties=["Medium"])
        pending_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")  # an eligible alternative

        await create_test_cycle(category, pending_map, status="pending")

        for _ in range(20):
            selected = await _select(asyncpg_pool, category)
            assert selected is not None
            assert selected != pending_map


class TestLruFallback:
    """When the eligible pool is exhausted, the LRU map is returned (not NULL)."""

    async def test_select_lru_fallback(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """All candidates within the blacklist window -> LRU fallback returns a map, never NULL.

        Uses the rare "Hell" grouping for the candidates created here. The suite runs
        under xdist (a shared DB across workers), so the *exact* global LRU map is not
        deterministic; this asserts the fallback behavior that matters: when the primary
        blacklist-filtered selection is empty, a non-NULL eligible map is still returned
        (rather than NULL), and it respects the category difficulty.
        """
        await _set_blacklist_weeks(asyncpg_pool, 8)
        category = await create_test_category(difficulties=["Hell"])

        older_map = await create_test_map(difficulty="Hell")
        newer_map = await create_test_map(difficulty="Hell")

        # Both used within the 8-week window -> primary (blacklist-filtered) selection
        # would exclude them; the LRU fallback (which ignores the window) engages.
        await create_test_cycle(category, older_map, status="completed", started_at=_days_ago(40))
        await create_test_cycle(category, newer_map, status="completed", started_at=_days_ago(5))

        # Confirm the primary selection is exhausted for *our* maps: neither is eligible
        # via the windowed path, so any non-NULL result proves the LRU fallback fired.
        selected = await _select(asyncpg_pool, category)
        assert selected is not None
        assert await _base_difficulty(asyncpg_pool, selected) == "Hell"

        # The fallback prefers the least-recently-used map. If the global pick happens
        # to be one of our pair, it must be the older (less-recently-used) one -- it must
        # never be the more-recently-used newer_map. (Parallel-safe: other workers' Hell
        # maps may sort ahead via NULLS FIRST, but our newer_map must never win over
        # our older_map.)
        assert selected != newer_map


class TestNoEligibleMaps:
    """The helper returns NULL when no maps match the category difficulties."""

    async def test_select_returns_null_when_no_maps(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_map,
    ):
        """A category whose difficulties match zero maps yields NULL (drives D-07 skip).

        Uses the rare "Extreme +" grouping with zero maps created for it.
        """
        category = await create_test_category(difficulties=["Extreme +"])
        # Maps that do NOT match the category difficulty.
        await create_test_map(difficulty="Easy")
        await create_test_map(difficulty="Medium")

        selected = await _select(asyncpg_pool, category)
        assert selected is None


class TestPythonParity:
    """The SQL helper's pick is within the Python fetch_eligible_maps eligibility set."""

    async def test_parity_with_python_eligible(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """SQL select_eligible_map returns an id within the live Python-eligible set (D-06).

        Both queries run against the same shared DB, so this membership check holds
        regardless of maps created by other tests: whatever the SQL helper picks must
        also be eligible per the Python path.
        """
        await _set_blacklist_weeks(asyncpg_pool, 4)
        category = await create_test_category(difficulties=["Medium"])

        # Eligible maps (matching difficulty, not in window, not pending).
        eligible_a = await create_test_map(difficulty="Medium")
        eligible_b = await create_test_map(difficulty="Medium +")  # normalizes to Medium
        # Excluded: in blacklist window.
        in_window = await create_test_map(difficulty="Medium")
        await create_test_cycle(category, in_window, status="completed", started_at=_days_ago(3))
        # Excluded: pending cycle.
        pending = await create_test_map(difficulty="Medium")
        await create_test_cycle(category, pending, status="pending")
        # Excluded: wrong difficulty.
        await create_test_map(difficulty="Hard")

        repository = TournamentRepository(asyncpg_pool)
        async with asyncpg_pool.acquire() as conn:
            python_rows = await repository.fetch_eligible_maps(
                ["Medium"],
                4,
                conn=conn,  # type: ignore[arg-type]
            )
        python_eligible = {row["id"] for row in python_rows}

        # The eligible maps we created appear in the Python-eligible set; the excluded
        # ones do not.
        assert {eligible_a, eligible_b} <= python_eligible
        assert in_window not in python_eligible
        assert pending not in python_eligible

        # SQL helper picks must be a subset of the Python eligible set (membership parity;
        # exact pick differs because both use ORDER BY random()).
        for _ in range(20):
            selected = await _select(asyncpg_pool, category)
            assert selected in python_eligible
