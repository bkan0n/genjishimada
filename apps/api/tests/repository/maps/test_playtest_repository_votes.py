"""Tests for PlaytestRepository vote operations.

Test Coverage:
- cast_vote: Create and update votes with constraint validation
- fetch_playtest_votes: Retrieve all votes for a playtest
- check_vote_exists: Check if user has voted
- delete_vote: Delete single vote
- delete_all_votes: Delete all votes for playtest
- get_average_difficulty: Calculate average from votes
"""

import asyncpg
import pytest
from faker import Faker

from repository.exceptions import CheckConstraintViolationError
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
# HELPER FIXTURES
# ==============================================================================


@pytest.fixture
async def create_completion(asyncpg_conn):
    """Factory to create a verified completion for voting."""

    async def _create(user_id: int, map_id: int) -> int:
        completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, verified, legacy, time, screenshot, completion
            )
            VALUES ($1, $2, TRUE, FALSE, 30.5, 'https://example.com/screenshot.png', TRUE)
            RETURNING id
            """,
            user_id,
            map_id,
        )
        return completion_id

    return _create


# ==============================================================================
# CAST VOTE TESTS
# ==============================================================================


class TestCastVoteHappyPath:
    """Test successful vote casting scenarios."""

    @pytest.mark.asyncio
    async def test_cast_vote_creates_new_vote(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test casting a vote creates a new record."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)

        difficulty = 7.5

        # Act
        await repository.cast_vote(unique_thread_id, user_id, difficulty)

        # Assert - verify vote was created
        vote = await asyncpg_conn.fetchrow(
            "SELECT * FROM playtests.votes WHERE playtest_thread_id = $1 AND user_id = $2",
            unique_thread_id,
            user_id,
        )
        assert vote is not None
        assert float(vote["difficulty"]) == difficulty
        assert vote["map_id"] == map_id

    @pytest.mark.asyncio
    async def test_cast_vote_updates_existing_vote(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test casting a vote updates existing vote (upsert)."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)

        # Cast initial vote
        await repository.cast_vote(unique_thread_id, user_id, 5.0)

        # Act - update vote
        new_difficulty = 8.5
        await repository.cast_vote(unique_thread_id, user_id, new_difficulty)

        # Assert - verify vote was updated, not duplicated
        votes = await asyncpg_conn.fetch(
            "SELECT * FROM playtests.votes WHERE playtest_thread_id = $1 AND user_id = $2",
            unique_thread_id,
            user_id,
        )
        assert len(votes) == 1  # Only one vote
        assert float(votes[0]["difficulty"]) == new_difficulty

    @pytest.mark.asyncio
    async def test_cast_vote_with_minimum_difficulty(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test casting vote with minimum valid difficulty (0)."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)

        # Act & Assert - should not raise
        await repository.cast_vote(unique_thread_id, user_id, 0.0)

    @pytest.mark.asyncio
    async def test_cast_vote_with_maximum_difficulty(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test casting vote with maximum valid difficulty (10)."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)

        # Act & Assert - should not raise
        await repository.cast_vote(unique_thread_id, user_id, 10.0)

    @pytest.mark.asyncio
    async def test_cast_vote_with_decimal_precision(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test casting vote with decimal precision (numeric(4,2))."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)

        difficulty = 7.25

        # Act
        await repository.cast_vote(unique_thread_id, user_id, difficulty)

        # Assert
        vote = await asyncpg_conn.fetchrow(
            "SELECT difficulty FROM playtests.votes WHERE playtest_thread_id = $1 AND user_id = $2",
            unique_thread_id,
            user_id,
        )
        assert float(vote["difficulty"]) == difficulty


class TestCastVoteConstraintViolations:
    """Test vote constraint violations."""

    @pytest.mark.asyncio
    async def test_cast_vote_without_completion_raises_error(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test casting vote without verified completion raises CheckConstraintViolationError."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        # Note: No completion created

        # Act & Assert
        with pytest.raises(CheckConstraintViolationError):
            await repository.cast_vote(unique_thread_id, user_id, 5.0)

    @pytest.mark.asyncio
    async def test_cast_vote_with_legacy_completion_raises_error(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test casting vote with legacy completion raises error."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create legacy completion (should not allow vote)
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (user_id, map_id, verified, legacy, time, screenshot, completion)
            VALUES ($1, $2, TRUE, TRUE, 30.5, 'https://example.com/screenshot.png', TRUE)
            """,
            user_id,
            map_id,
        )

        # Act & Assert
        with pytest.raises(CheckConstraintViolationError):
            await repository.cast_vote(unique_thread_id, user_id, 5.0)

    @pytest.mark.asyncio
    async def test_cast_vote_with_unverified_completion_raises_error(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test casting vote with unverified completion raises error."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create unverified completion
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (user_id, map_id, verified, legacy, time, screenshot, completion)
            VALUES ($1, $2, FALSE, FALSE, 30.5, 'https://example.com/screenshot.png', TRUE)
            """,
            user_id,
            map_id,
        )

        # Act & Assert
        with pytest.raises(CheckConstraintViolationError):
            await repository.cast_vote(unique_thread_id, user_id, 5.0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_difficulty", [-0.01, -1.0, 10.01, 11.0])
    async def test_cast_vote_with_invalid_difficulty_raises_error(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        invalid_difficulty: float,
    ) -> None:
        """Test casting vote with out-of-range difficulty raises CheckConstraintViolationError."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)

        # Act & Assert
        with pytest.raises(CheckConstraintViolationError) as exc_info:
            await repository.cast_vote(unique_thread_id, user_id, invalid_difficulty)

        assert "difficulty_range" in exc_info.value.constraint_name


# ==============================================================================
# FETCH PLAYTEST VOTES TESTS
# ==============================================================================


class TestFetchPlaytestVotes:
    """Test fetching votes for a playtest."""

    @pytest.mark.asyncio
    async def test_fetch_votes_returns_list_with_user_info(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test fetch_playtest_votes returns votes with user names."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user(nickname="TestVoter")
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)
        await repository.cast_vote(unique_thread_id, user_id, 7.5)

        # Act
        votes = await repository.fetch_playtest_votes(unique_thread_id)

        # Assert
        assert len(votes) == 1
        assert votes[0]["user_id"] == user_id
        assert float(votes[0]["difficulty"]) == 7.5
        assert votes[0]["name"] == "TestVoter"

    @pytest.mark.asyncio
    async def test_fetch_votes_returns_empty_list_when_no_votes(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test fetch_playtest_votes returns empty list when no votes exist."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act
        votes = await repository.fetch_playtest_votes(unique_thread_id)

        # Assert
        assert votes == []

    @pytest.mark.asyncio
    async def test_fetch_votes_returns_multiple_votes(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test fetch_playtest_votes returns all votes for playtest."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        user3_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await create_completion(user1_id, map_id)
        await create_completion(user2_id, map_id)
        await create_completion(user3_id, map_id)

        await repository.cast_vote(unique_thread_id, user1_id, 5.0)
        await repository.cast_vote(unique_thread_id, user2_id, 7.0)
        await repository.cast_vote(unique_thread_id, user3_id, 9.0)

        # Act
        votes = await repository.fetch_playtest_votes(unique_thread_id)

        # Assert
        assert len(votes) == 3
        user_ids = {vote["user_id"] for vote in votes}
        assert user_ids == {user1_id, user2_id, user3_id}


# ==============================================================================
# CHECK VOTE EXISTS TESTS
# ==============================================================================


class TestCheckVoteExists:
    """Test checking if vote exists."""

    @pytest.mark.asyncio
    async def test_check_vote_exists_returns_true_when_vote_exists(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test check_vote_exists returns True when vote exists."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)
        await repository.cast_vote(unique_thread_id, user_id, 7.5)

        # Act
        exists = await repository.check_vote_exists(unique_thread_id, user_id)

        # Assert
        assert exists is True

    @pytest.mark.asyncio
    async def test_check_vote_exists_returns_false_when_no_vote(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test check_vote_exists returns False when user hasn't voted."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act
        exists = await repository.check_vote_exists(unique_thread_id, user_id)

        # Assert
        assert exists is False

    @pytest.mark.asyncio
    async def test_check_vote_exists_returns_false_for_non_existent_thread(
        self,
        repository: PlaytestRepository,
        create_test_user,
    ) -> None:
        """Test check_vote_exists returns False for non-existent thread."""
        # Arrange
        user_id = await create_test_user()
        non_existent_thread_id = 999999999999999999

        # Act
        exists = await repository.check_vote_exists(non_existent_thread_id, user_id)

        # Assert
        assert exists is False


# ==============================================================================
# DELETE VOTE TESTS
# ==============================================================================


class TestDeleteVote:
    """Test deleting single votes."""

    @pytest.mark.asyncio
    async def test_delete_vote_removes_vote(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test delete_vote removes the user's vote."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)
        await repository.cast_vote(unique_thread_id, user_id, 7.5)

        # Act
        await repository.delete_vote(unique_thread_id, user_id)

        # Assert - verify vote is gone
        vote = await asyncpg_conn.fetchrow(
            "SELECT * FROM playtests.votes WHERE playtest_thread_id = $1 AND user_id = $2",
            unique_thread_id,
            user_id,
        )
        assert vote is None

    @pytest.mark.asyncio
    async def test_delete_vote_only_deletes_specific_user_vote(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test delete_vote only removes the specified user's vote."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await create_completion(user1_id, map_id)
        await create_completion(user2_id, map_id)
        await repository.cast_vote(unique_thread_id, user1_id, 5.0)
        await repository.cast_vote(unique_thread_id, user2_id, 7.0)

        # Act - delete user1's vote
        await repository.delete_vote(unique_thread_id, user1_id)

        # Assert - user2's vote still exists
        vote_count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM playtests.votes WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        assert vote_count == 1

        remaining_vote = await asyncpg_conn.fetchrow(
            "SELECT * FROM playtests.votes WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        assert remaining_vote["user_id"] == user2_id

    @pytest.mark.asyncio
    async def test_delete_vote_non_existent_is_no_op(
        self,
        repository: PlaytestRepository,
        create_test_user,
        unique_thread_id: int,
    ) -> None:
        """Test delete_vote is no-op when vote doesn't exist."""
        # Arrange
        user_id = await create_test_user()

        # Act & Assert - should not raise
        await repository.delete_vote(unique_thread_id, user_id)


# ==============================================================================
# DELETE ALL VOTES TESTS
# ==============================================================================


class TestDeleteAllVotes:
    """Test deleting all votes for a playtest."""

    @pytest.mark.asyncio
    async def test_delete_all_votes_removes_all_votes(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test delete_all_votes removes all votes for playtest."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        user3_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await create_completion(user1_id, map_id)
        await create_completion(user2_id, map_id)
        await create_completion(user3_id, map_id)

        await repository.cast_vote(unique_thread_id, user1_id, 5.0)
        await repository.cast_vote(unique_thread_id, user2_id, 7.0)
        await repository.cast_vote(unique_thread_id, user3_id, 9.0)

        # Act
        await repository.delete_all_votes(unique_thread_id)

        # Assert - no votes remain
        vote_count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM playtests.votes WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        assert vote_count == 0

    @pytest.mark.asyncio
    async def test_delete_all_votes_only_affects_specific_thread(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        global_thread_id_tracker: set[int],
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test delete_all_votes only deletes votes for specified thread."""
        # Arrange - create two playtests with votes
        map1_id = await create_test_map()
        map2_id = await create_test_map()
        user_id = await create_test_user()

        # Generate second thread ID
        while True:
            thread_id_2 = fake.random_int(min=100000000000000000, max=999999999999999999)
            if thread_id_2 not in global_thread_id_tracker:
                global_thread_id_tracker.add(thread_id_2)
                break

        await create_test_playtest(map1_id, thread_id=unique_thread_id)
        await create_test_playtest(map2_id, thread_id=thread_id_2)

        await create_completion(user_id, map1_id)
        await create_completion(user_id, map2_id)

        await repository.cast_vote(unique_thread_id, user_id, 5.0)
        await repository.cast_vote(thread_id_2, user_id, 7.0)

        # Act - delete votes for first thread only
        await repository.delete_all_votes(unique_thread_id)

        # Assert - second thread's vote still exists
        vote_count_thread1 = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM playtests.votes WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        vote_count_thread2 = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM playtests.votes WHERE playtest_thread_id = $1",
            thread_id_2,
        )
        assert vote_count_thread1 == 0
        assert vote_count_thread2 == 1

    @pytest.mark.asyncio
    async def test_delete_all_votes_when_no_votes_is_no_op(
        self,
        repository: PlaytestRepository,
        unique_thread_id: int,
    ) -> None:
        """Test delete_all_votes is no-op when no votes exist."""
        # Act & Assert - should not raise
        await repository.delete_all_votes(unique_thread_id)


# ==============================================================================
# GET AVERAGE DIFFICULTY TESTS
# ==============================================================================


class TestGetAverageDifficulty:
    """Test calculating average difficulty from votes."""

    @pytest.mark.asyncio
    async def test_get_average_difficulty_calculates_correctly(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test get_average_difficulty returns correct average."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        user3_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await create_completion(user1_id, map_id)
        await create_completion(user2_id, map_id)
        await create_completion(user3_id, map_id)

        await repository.cast_vote(unique_thread_id, user1_id, 4.0)
        await repository.cast_vote(unique_thread_id, user2_id, 6.0)
        await repository.cast_vote(unique_thread_id, user3_id, 8.0)

        # Act
        average = await repository.get_average_difficulty(unique_thread_id)

        # Assert - (4 + 6 + 8) / 3 = 6
        assert average is not None
        assert float(average) == 6.0

    @pytest.mark.asyncio
    async def test_get_average_difficulty_returns_none_when_no_votes(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test get_average_difficulty returns None when no votes exist."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act
        average = await repository.get_average_difficulty(unique_thread_id)

        # Assert
        assert average is None

    @pytest.mark.asyncio
    async def test_get_average_difficulty_with_single_vote(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test get_average_difficulty with single vote."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)
        await create_completion(user_id, map_id)
        await repository.cast_vote(unique_thread_id, user_id, 7.5)

        # Act
        average = await repository.get_average_difficulty(unique_thread_id)

        # Assert
        assert average is not None
        assert float(average) == 7.5

    @pytest.mark.asyncio
    async def test_get_average_difficulty_with_decimal_precision(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        create_completion,
    ) -> None:
        """Test get_average_difficulty handles decimal precision."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        await create_completion(user1_id, map_id)
        await create_completion(user2_id, map_id)

        await repository.cast_vote(unique_thread_id, user1_id, 5.25)
        await repository.cast_vote(unique_thread_id, user2_id, 7.75)

        # Act
        average = await repository.get_average_difficulty(unique_thread_id)

        # Assert - (5.25 + 7.75) / 2 = 6.5
        assert average is not None
        assert float(average) == 6.5
