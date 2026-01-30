"""Tests for CommunityRepository map-specific operations.

Test Coverage:
- fetch_map_completion_statistics
- fetch_map_record_progression
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.community_repository import CommunityRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_community,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide community repository instance."""
    return CommunityRepository(asyncpg_conn)


# ==============================================================================
# TESTS: fetch_map_completion_statistics
# ==============================================================================


class TestFetchMapCompletionStatistics:
    """Test fetch_map_completion_statistics method."""

    async def test_returns_empty_stats_for_nonexistent_map(
        self,
        repository: CommunityRepository,
    ) -> None:
        """Test that method returns empty list for non-existent map code."""
        # Arrange
        fake_code = f"T{uuid4().hex[:5].upper()}"

        # Act
        result = await repository.fetch_map_completion_statistics(fake_code)

        # Assert - Non-existent map returns empty list
        assert isinstance(result, list)
        assert len(result) == 0

    async def test_returns_empty_stats_for_map_with_no_completions(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that method returns None stats when map has no completions."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(code)

        # Act
        result = await repository.fetch_map_completion_statistics(code)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["min"] is None
        assert result[0]["max"] is None
        assert result[0]["avg"] is None

    async def test_calculates_stats_from_verified_completions(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that stats are calculated from verified completions."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user1 = await create_test_user()
        user2 = await create_test_user()
        user3 = await create_test_user()

        # Create verified completions with different times
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user1, 100.50, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user2, 200.75, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user3, 150.25, True, fake.url(), True
        )

        # Act
        result = await repository.fetch_map_completion_statistics(code)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1
        stats = result[0]
        assert stats["min"] == 100.50
        assert stats["max"] == 200.75
        # Average of 100.50, 200.75, 150.25 = 150.50
        assert stats["avg"] == 150.50

    async def test_excludes_unverified_completions(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that unverified completions are excluded from stats."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user1 = await create_test_user()
        user2 = await create_test_user()

        # Create one verified and one unverified completion
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user1, 100.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user2, 50.0, False, fake.url(), True  # Unverified, lower time
        )

        # Act
        result = await repository.fetch_map_completion_statistics(code)

        # Assert - Should only count verified completion
        assert isinstance(result, list)
        assert len(result) == 1
        stats = result[0]
        assert stats["min"] == 100.0
        assert stats["max"] == 100.0
        assert stats["avg"] == 100.0

    async def test_excludes_invalid_times(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that times >= 99999999.99 are excluded from stats."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user1 = await create_test_user()
        user2 = await create_test_user()

        # Create one valid and one invalid time
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user1, 100.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user2, 99999999.99, True, fake.url(), True  # At threshold
        )

        # Act
        result = await repository.fetch_map_completion_statistics(code)

        # Assert - Should only count valid time
        assert isinstance(result, list)
        assert len(result) == 1
        stats = result[0]
        assert stats["min"] == 100.0
        assert stats["max"] == 100.0
        assert stats["avg"] == 100.0

    async def test_rounds_to_two_decimal_places(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that stats are rounded to 2 decimal places."""
        from decimal import Decimal

        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user1 = await create_test_user()
        user2 = await create_test_user()
        user3 = await create_test_user()

        # Create completions that will produce non-round average
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user1, 100.333, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user2, 200.666, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user3, 150.999, True, fake.url(), True
        )

        # Act
        result = await repository.fetch_map_completion_statistics(code)

        # Assert - All values should be rounded to 2 decimals
        assert isinstance(result, list)
        assert len(result) == 1
        stats = result[0]
        # Values come back as Decimal, so compare to Decimal
        # min(100.333, 200.666, 150.999) = 100.333 → rounds to 100.33
        # max(100.333, 200.666, 150.999) = 200.666 → rounds to 200.67
        # avg = (100.333 + 200.666 + 150.999) / 3 = 150.666 → rounds to 150.67
        assert stats["min"] == Decimal("100.33")
        assert stats["max"] == Decimal("200.67")
        assert stats["avg"] == Decimal("150.67")


# ==============================================================================
# TESTS: fetch_map_record_progression
# ==============================================================================


class TestFetchMapRecordProgression:
    """Test fetch_map_record_progression method."""

    async def test_returns_empty_for_nonexistent_map(
        self,
        repository: CommunityRepository,
        create_test_user,
    ) -> None:
        """Test that method returns empty list for non-existent map."""
        # Arrange
        user_id = await create_test_user()
        fake_code = f"T{uuid4().hex[:5].upper()}"

        # Act
        result = await repository.fetch_map_record_progression(user_id, fake_code)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    async def test_returns_empty_for_user_with_no_records(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
    ) -> None:
        """Test that method returns empty list when user has no records."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(code)
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_map_record_progression(user_id, code)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    async def test_returns_records_ordered_by_time_ascending(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that records are returned ordered by time ascending."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user_id = await create_test_user()

        # Create records with times in non-chronological order
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion, inserted_at)
            VALUES ($1, $2, $3, $4, $5, $6, now() - interval '3 days')
            """,
            map_id, user_id, 200.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion, inserted_at)
            VALUES ($1, $2, $3, $4, $5, $6, now() - interval '2 days')
            """,
            map_id, user_id, 150.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion, inserted_at)
            VALUES ($1, $2, $3, $4, $5, $6, now() - interval '1 day')
            """,
            map_id, user_id, 100.0, True, fake.url(), True
        )

        # Act
        result = await repository.fetch_map_record_progression(user_id, code)

        # Assert - Should be ordered by time (100, 150, 200)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["time"] == 100.0
        assert result[1]["time"] == 150.0
        assert result[2]["time"] == 200.0

    async def test_excludes_invalid_times(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that times >= 99999999.99 are excluded."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user_id = await create_test_user()

        # Create one valid and one invalid time
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user_id, 100.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user_id, 99999999.99, True, fake.url(), True
        )

        # Act
        result = await repository.fetch_map_record_progression(user_id, code)

        # Assert - Should only return valid time
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["time"] == 100.0

    async def test_includes_both_verified_and_unverified(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that both verified and unverified records are included."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user_id = await create_test_user()

        # Create verified and unverified records
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user_id, 100.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user_id, 90.0, False, fake.url(), True
        )

        # Act
        result = await repository.fetch_map_record_progression(user_id, code)

        # Assert - Should return both
        assert isinstance(result, list)
        assert len(result) == 2

    async def test_returns_only_records_for_specified_user(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that only records for the specified user are returned."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user1 = await create_test_user()
        user2 = await create_test_user()

        # Create records for both users
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user1, 100.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user2, 90.0, True, fake.url(), True
        )

        # Act - Query for user1
        result = await repository.fetch_map_record_progression(user1, code)

        # Assert - Should only return user1's record
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["time"] == 100.0

    async def test_includes_inserted_at_timestamp(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test that inserted_at timestamp is included in results."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code)
        user_id = await create_test_user()

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map_id, user_id, 100.0, True, fake.url(), True
        )

        # Act
        result = await repository.fetch_map_record_progression(user_id, code)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 1
        assert "time" in result[0]
        assert "inserted_at" in result[0]
        assert result[0]["inserted_at"] is not None
