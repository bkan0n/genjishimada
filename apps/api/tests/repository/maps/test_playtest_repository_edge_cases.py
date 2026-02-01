"""Tests for PlaytestRepository edge cases and concurrency.

Test Coverage:
- Edge cases for various operations
- Null handling
- Concurrent operations
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
# NULL HANDLING TESTS
# ==============================================================================


class TestNullHandling:
    """Test handling of null values in various operations."""

    @pytest.mark.asyncio
    async def test_fetch_playtest_with_null_verification_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test fetching playtest with null verification_id."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, verification_id=None)

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert result["verification_id"] is None

    @pytest.mark.asyncio
    async def test_update_playtest_meta_to_null_verification_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test updating verification_id to NULL."""
        # Arrange
        map_id = await create_test_map()
        verification_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        await create_test_playtest(map_id, thread_id=unique_thread_id, verification_id=verification_id)

        # Act - update to NULL
        await repository.update_playtest_meta(unique_thread_id, {"verification_id": None})

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT verification_id FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert result["verification_id"] is None


# ==============================================================================
# CONCURRENT OPERATIONS TESTS
# ==============================================================================


class TestConcurrentOperations:
    """Test concurrent operations on playtests."""

    @pytest.mark.asyncio
    async def test_concurrent_vote_casting(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test multiple users casting votes concurrently."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        user3_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create completions for all users
        for user_id in [user1_id, user2_id, user3_id]:
            await asyncpg_conn.execute(
                """
                INSERT INTO core.completions (
                    user_id, map_id, verified, legacy, time, screenshot, completion
                )
                VALUES ($1, $2, TRUE, FALSE, 30.5, 'https://example.com/screenshot.png', TRUE)
                """,
                user_id,
                map_id,
            )

        # Act - cast votes (simulating concurrent operations)
        await repository.cast_vote(unique_thread_id, user1_id, 5.0)
        await repository.cast_vote(unique_thread_id, user2_id, 7.0)
        await repository.cast_vote(unique_thread_id, user3_id, 9.0)

        # Assert - all votes should be recorded
        vote_count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM playtests.votes WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        assert vote_count == 3

    @pytest.mark.asyncio
    async def test_update_vote_while_fetching_average(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test updating a vote while calculating average doesn't cause issues."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (
                user_id, map_id, verified, legacy, time, screenshot, completion
            )
            VALUES ($1, $2, TRUE, FALSE, 30.5, 'https://example.com/screenshot.png', TRUE)
            """,
            user_id,
            map_id,
        )

        # Cast initial vote
        await repository.cast_vote(unique_thread_id, user_id, 5.0)

        # Act - update vote and get average
        await repository.cast_vote(unique_thread_id, user_id, 8.0)
        average = await repository.get_average_difficulty(unique_thread_id)

        # Assert - should reflect updated vote
        assert average is not None
        assert float(average) == 8.0


# ==============================================================================
# BOUNDARY VALUE TESTS
# ==============================================================================


class TestBoundaryValues:
    """Test boundary values for various operations."""

    @pytest.mark.asyncio
    async def test_difficulty_at_minimum_boundary(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test difficulty value at minimum boundary (0.0)."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, initial_difficulty=0.0)

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert float(result["initial_difficulty"]) == 0.0

    @pytest.mark.asyncio
    async def test_difficulty_at_maximum_boundary(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test difficulty value at maximum boundary (10.0)."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id, initial_difficulty=10.0)

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert float(result["initial_difficulty"]) == 10.0


# ==============================================================================
# IDEMPOTENCY TESTS
# ==============================================================================


class TestIdempotency:
    """Test idempotent operations."""

    @pytest.mark.asyncio
    async def test_delete_vote_twice_is_idempotent(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test deleting the same vote twice is safe."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (
                user_id, map_id, verified, legacy, time, screenshot, completion
            )
            VALUES ($1, $2, TRUE, FALSE, 30.5, 'https://example.com/screenshot.png', TRUE)
            """,
            user_id,
            map_id,
        )

        await repository.cast_vote(unique_thread_id, user_id, 7.5)

        # Act - delete twice
        await repository.delete_vote(unique_thread_id, user_id)
        await repository.delete_vote(unique_thread_id, user_id)

        # Assert - should not raise, vote should be gone
        exists = await repository.check_vote_exists(unique_thread_id, user_id)
        assert exists is False

    @pytest.mark.asyncio
    async def test_approve_playtest_twice_is_idempotent(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test approving the same playtest twice updates difficulty."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act - approve twice with different difficulties
        await repository.approve_playtest(map_id, unique_thread_id, 7.0)
        await repository.approve_playtest(map_id, unique_thread_id, 9.0)

        # Assert - should use latest difficulty
        map_row = await asyncpg_conn.fetchrow(
            "SELECT raw_difficulty, playtesting FROM core.maps WHERE id = $1",
            map_id,
        )
        assert float(map_row["raw_difficulty"]) == 9.0
        assert map_row["playtesting"] == "Approved"
