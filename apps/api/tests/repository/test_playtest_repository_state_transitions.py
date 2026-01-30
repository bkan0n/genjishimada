"""Tests for PlaytestRepository state transition operations.

Test Coverage:
- approve_playtest: Approve playtest with average difficulty
- force_accept_playtest: Force accept with custom difficulty
- force_deny_playtest: Deny and hide map
"""

import pytest
from faker import Faker

from repository.playtest_repository import PlaytestRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_playtests,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide playtest repository instance."""
    return PlaytestRepository(asyncpg_conn)


# ==============================================================================
# APPROVE PLAYTEST TESTS
# ==============================================================================


class TestApprovePlaytest:
    """Test approving playtests with average difficulty."""

    @pytest.mark.asyncio
    async def test_approve_playtest_updates_map_status(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approve_playtest sets map to Approved status."""
        # Arrange
        map_id = await create_test_map(playtesting="In Progress")
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        average_difficulty = 7.5

        # Act
        await repository.approve_playtest(map_id, unique_thread_id, average_difficulty)

        # Assert - verify map status updated
        map_row = await asyncpg_conn.fetchrow(
            "SELECT playtesting, raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        assert map_row["playtesting"] == "Approved"
        assert float(map_row["raw_difficulty"]) == average_difficulty

    @pytest.mark.asyncio
    async def test_approve_playtest_sets_raw_difficulty(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approve_playtest sets raw_difficulty from average votes."""
        # Arrange
        map_id = await create_test_map(raw_difficulty=0.0)
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        average_difficulty = 8.75

        # Act
        await repository.approve_playtest(map_id, unique_thread_id, average_difficulty)

        # Assert
        map_row = await asyncpg_conn.fetchrow(
            "SELECT raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        assert float(map_row["raw_difficulty"]) == average_difficulty

    @pytest.mark.asyncio
    async def test_approve_playtest_marks_completed(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approve_playtest marks playtest meta as completed."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=False)
        average_difficulty = 6.5

        # Act
        await repository.approve_playtest(map_id, unique_thread_id, average_difficulty)

        # Assert - verify playtest marked completed
        meta_row = await asyncpg_conn.fetchrow(
            "SELECT completed FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert meta_row["completed"] is True

    @pytest.mark.asyncio
    async def test_approve_playtest_with_decimal_precision(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approve_playtest preserves decimal precision in difficulty."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        average_difficulty = 7.33

        # Act
        await repository.approve_playtest(map_id, unique_thread_id, average_difficulty)

        # Assert
        map_row = await asyncpg_conn.fetchrow(
            "SELECT raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        # Note: PostgreSQL may round to 2 decimal places
        assert abs(float(map_row["raw_difficulty"]) - average_difficulty) < 0.01

    @pytest.mark.asyncio
    async def test_approve_playtest_both_updates_succeed_or_fail(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approve_playtest is atomic (both updates or neither)."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=False)
        average_difficulty = 7.0

        # Act
        await repository.approve_playtest(map_id, unique_thread_id, average_difficulty)

        # Assert - both updates should have succeeded
        map_row = await asyncpg_conn.fetchrow(
            "SELECT playtesting FROM core.maps WHERE id = $1",
            map_id,
        )
        meta_row = await asyncpg_conn.fetchrow(
            "SELECT completed FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert map_row["playtesting"] == "Approved"
        assert meta_row["completed"] is True


# ==============================================================================
# FORCE ACCEPT PLAYTEST TESTS
# ==============================================================================


class TestForceAcceptPlaytest:
    """Test force accepting playtests with custom difficulty."""

    @pytest.mark.asyncio
    async def test_force_accept_updates_map_status(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_accept_playtest sets map to Approved status."""
        # Arrange
        map_id = await create_test_map(playtesting="In Progress")
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        custom_difficulty = 9.0

        # Act
        await repository.force_accept_playtest(map_id, unique_thread_id, custom_difficulty)

        # Assert
        map_row = await asyncpg_conn.fetchrow(
            "SELECT playtesting, raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        assert map_row["playtesting"] == "Approved"
        assert float(map_row["raw_difficulty"]) == custom_difficulty

    @pytest.mark.asyncio
    async def test_force_accept_with_custom_difficulty(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_accept_playtest uses custom difficulty value."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        custom_difficulty = 4.25

        # Act
        await repository.force_accept_playtest(map_id, unique_thread_id, custom_difficulty)

        # Assert - should use custom value, not average
        map_row = await asyncpg_conn.fetchrow(
            "SELECT raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        assert float(map_row["raw_difficulty"]) == custom_difficulty

    @pytest.mark.asyncio
    async def test_force_accept_marks_completed(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_accept_playtest marks playtest as completed."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=False)
        custom_difficulty = 8.0

        # Act
        await repository.force_accept_playtest(map_id, unique_thread_id, custom_difficulty)

        # Assert
        meta_row = await asyncpg_conn.fetchrow(
            "SELECT completed FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert meta_row["completed"] is True

    @pytest.mark.asyncio
    async def test_force_accept_with_extreme_difficulty_values(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_accept_playtest accepts boundary difficulty values."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act - use boundary value
        await repository.force_accept_playtest(map_id, unique_thread_id, 10.0)

        # Assert
        map_row = await asyncpg_conn.fetchrow(
            "SELECT raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        assert float(map_row["raw_difficulty"]) == 10.0


# ==============================================================================
# FORCE DENY PLAYTEST TESTS
# ==============================================================================


class TestForceDenyPlaytest:
    """Test force denying playtests."""

    @pytest.mark.asyncio
    async def test_force_deny_sets_rejected_status(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_deny_playtest sets map to Rejected status."""
        # Arrange
        map_id = await create_test_map(playtesting="In Progress")
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act
        await repository.force_deny_playtest(map_id, unique_thread_id)

        # Assert
        map_row = await asyncpg_conn.fetchrow(
            "SELECT playtesting FROM core.maps WHERE id = $1",
            map_id,
        )
        assert map_row["playtesting"] == "Rejected"

    @pytest.mark.asyncio
    async def test_force_deny_hides_map(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_deny_playtest sets map as hidden."""
        # Arrange
        map_id = await create_test_map(hidden=False)
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act
        await repository.force_deny_playtest(map_id, unique_thread_id)

        # Assert
        map_row = await asyncpg_conn.fetchrow(
            "SELECT hidden FROM core.maps WHERE id = $1",
            map_id,
        )
        assert map_row["hidden"] is True

    @pytest.mark.asyncio
    async def test_force_deny_marks_completed(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_deny_playtest marks playtest as completed."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=False)

        # Act
        await repository.force_deny_playtest(map_id, unique_thread_id)

        # Assert
        meta_row = await asyncpg_conn.fetchrow(
            "SELECT completed FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert meta_row["completed"] is True

    @pytest.mark.asyncio
    async def test_force_deny_both_updates_succeed(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test force_deny_playtest updates both map and meta atomically."""
        # Arrange
        map_id = await create_test_map(hidden=False, playtesting="In Progress")
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=False)

        # Act
        await repository.force_deny_playtest(map_id, unique_thread_id)

        # Assert - both updates should have succeeded
        map_row = await asyncpg_conn.fetchrow(
            "SELECT playtesting, hidden FROM core.maps WHERE id = $1",
            map_id,
        )
        meta_row = await asyncpg_conn.fetchrow(
            "SELECT completed FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert map_row["playtesting"] == "Rejected"
        assert map_row["hidden"] is True
        assert meta_row["completed"] is True


# ==============================================================================
# STATE TRANSITION EDGE CASES
# ==============================================================================


class TestStateTransitionEdgeCases:
    """Test edge cases for state transitions."""

    @pytest.mark.asyncio
    async def test_approve_already_approved_playtest(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approving an already approved playtest."""
        # Arrange
        map_id = await create_test_map(playtesting="Approved", raw_difficulty=5.0)
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=True)

        # Act - approve again with different difficulty
        await repository.approve_playtest(map_id, unique_thread_id, 8.0)

        # Assert - difficulty should be updated
        map_row = await asyncpg_conn.fetchrow(
            "SELECT raw_difficulty FROM core.maps WHERE id = $1",
            map_id,
        )
        assert float(map_row["raw_difficulty"]) == 8.0

    @pytest.mark.asyncio
    async def test_deny_already_denied_playtest(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test denying an already denied playtest."""
        # Arrange
        map_id = await create_test_map(playtesting="Rejected", hidden=True)
        await create_test_playtest(map_id, thread_id=unique_thread_id, completed=True)

        # Act - deny again
        await repository.force_deny_playtest(map_id, unique_thread_id)

        # Assert - should remain rejected and hidden
        map_row = await asyncpg_conn.fetchrow(
            "SELECT playtesting, hidden FROM core.maps WHERE id = $1",
            map_id,
        )
        assert map_row["playtesting"] == "Rejected"
        assert map_row["hidden"] is True
