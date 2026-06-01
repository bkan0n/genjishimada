"""Integration tests for the cycle lifecycle-control repository methods.

Covers check_any_live_cycle, create_active_cycle, set_category_paused, and
set_category_debug_cycle_seconds added in quick-task 260601-bhy. Uses the same
conftest fixtures (create_test_category, create_test_cycle, create_test_map) as
the rest of the tournaments repository suite.
"""

import asyncpg
import pytest

from repository.tournaments_repository import TournamentRepository

pytestmark = [pytest.mark.domain_tournaments]


class TestCheckAnyLiveCycle:
    """check_any_live_cycle returns a cycle id for any non-completed cycle."""

    async def test_returns_none_for_fresh_category(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
    ):
        """A category with no cycles has no live cycle."""
        category = await create_test_category()
        repo = TournamentRepository(asyncpg_pool)
        assert await repo.check_any_live_cycle(category) is None

    @pytest.mark.parametrize("status", ["active", "finalizing", "pending"])
    async def test_returns_id_for_live_cycle(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
        status: str,
    ):
        """A category with an active/finalizing/pending cycle returns that id."""
        category = await create_test_category()
        map_id = await create_test_map(difficulty="Medium")
        cycle = await create_test_cycle(category, map_id, status=status)

        repo = TournamentRepository(asyncpg_pool)
        assert await repo.check_any_live_cycle(category) == cycle

    async def test_returns_none_for_completed_only(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A category whose only cycle is completed is not 'live'."""
        category = await create_test_category()
        map_id = await create_test_map(difficulty="Medium")
        await create_test_cycle(category, map_id, status="completed")

        repo = TournamentRepository(asyncpg_pool)
        assert await repo.check_any_live_cycle(category) is None


class TestCreateActiveCycle:
    """create_active_cycle creates an active cycle with a started_at."""

    async def test_creates_active_cycle(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_map,
    ):
        """The created cycle is active with a non-null started_at."""
        category = await create_test_category()
        map_id = await create_test_map(difficulty="Medium")

        repo = TournamentRepository(asyncpg_pool)
        row = await repo.create_active_cycle(category, map_id)

        assert row["status"] == "active"
        assert row["started_at"] is not None
        assert row["category_id"] == category
        assert row["map_id"] == map_id


class TestSetCategoryPaused:
    """set_category_paused flips and round-trips the transitions_paused flag."""

    async def test_flip_and_round_trip(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
    ):
        """Pausing then resuming round-trips the flag."""
        category = await create_test_category()
        repo = TournamentRepository(asyncpg_pool)

        paused = await repo.set_category_paused(category, True)
        assert paused is not None
        assert paused["transitions_paused"] is True

        resumed = await repo.set_category_paused(category, False)
        assert resumed is not None
        assert resumed["transitions_paused"] is False

    async def test_missing_category_returns_none(
        self,
        asyncpg_pool: asyncpg.Pool,
    ):
        """Updating a non-existent category returns None."""
        repo = TournamentRepository(asyncpg_pool)
        assert await repo.set_category_paused(999_999, True) is None


class TestSetCategoryDebugCycleSeconds:
    """set_category_debug_cycle_seconds sets and clears the override."""

    async def test_set_and_clear(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
    ):
        """Setting an override then clearing it (None) round-trips."""
        category = await create_test_category()
        repo = TournamentRepository(asyncpg_pool)

        set_row = await repo.set_category_debug_cycle_seconds(category, 30)
        assert set_row is not None
        assert set_row["debug_cycle_seconds"] == 30

        cleared = await repo.set_category_debug_cycle_seconds(category, None)
        assert cleared is not None
        assert cleared["debug_cycle_seconds"] is None

    async def test_missing_category_returns_none(
        self,
        asyncpg_pool: asyncpg.Pool,
    ):
        """Updating a non-existent category returns None."""
        repo = TournamentRepository(asyncpg_pool)
        assert await repo.set_category_debug_cycle_seconds(999_999, 30) is None
