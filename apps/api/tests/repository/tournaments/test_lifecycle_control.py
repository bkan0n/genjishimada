"""Integration tests for the cycle lifecycle-control repository methods.

Covers check_any_live_cycle and create_active_cycle. The per-category
set_category_paused / set_category_debug_cycle_seconds tests were removed in
Phase 12 — pause/debug went GLOBAL (D-03), and the global setters are now
covered by test_tournaments_repository.py (test_set_transitions_paused,
test_set_debug_cycle_seconds_and_clear). Uses the same conftest fixtures
(create_test_category, create_test_cycle, create_test_map) as the rest of the
tournaments repository suite.
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
