"""Tests for PlaytestRepository read operations.

Test Coverage:
- fetch_playtest: Fetch playtest metadata by thread ID
- get_map_id_from_thread: Get map ID from playtest thread
- get_primary_creator: Get primary creator for a map
- get_map_code: Get map code from map ID
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
# FETCH PLAYTEST TESTS
# ==============================================================================


class TestFetchPlaytest:
    """Test fetching playtest metadata."""

    @pytest.mark.asyncio
    async def test_fetch_playtest_returns_metadata_with_map_code(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        unique_map_code: str,
    ) -> None:
        """Test fetch_playtest returns complete metadata with map code."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        playtest_id = await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            initial_difficulty=7.5,
        )

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert result["id"] == playtest_id
        assert result["thread_id"] == unique_thread_id
        assert result["code"] == unique_map_code
        assert float(result["initial_difficulty"]) == 7.5
        assert result["completed"] is False
        assert "created_at" in result
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_fetch_playtest_returns_none_for_non_existent_thread(
        self,
        repository: PlaytestRepository,
    ) -> None:
        """Test fetch_playtest returns None when thread doesn't exist."""
        # Arrange
        non_existent_thread_id = 999999999999999999

        # Act
        result = await repository.fetch_playtest(non_existent_thread_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_playtest_includes_verification_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test fetch_playtest includes verification_id when set."""
        # Arrange
        map_id = await create_test_map()
        verification_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            verification_id=verification_id,
        )

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert result["verification_id"] == verification_id

    @pytest.mark.asyncio
    async def test_fetch_playtest_with_null_verification_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test fetch_playtest handles null verification_id."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            verification_id=None,
        )

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert result["verification_id"] is None

    @pytest.mark.asyncio
    async def test_fetch_playtest_when_completed(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test fetch_playtest returns correct completed status."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            completed=True,
        )

        # Act
        result = await repository.fetch_playtest(unique_thread_id)

        # Assert
        assert result is not None
        assert result["completed"] is True


# ==============================================================================
# GET MAP ID FROM THREAD TESTS
# ==============================================================================


class TestGetMapIdFromThread:
    """Test getting map ID from playtest thread."""

    @pytest.mark.asyncio
    async def test_get_map_id_from_thread_returns_map_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test get_map_id_from_thread returns correct map ID."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act
        result = await repository.get_map_id_from_thread(unique_thread_id)

        # Assert
        assert result == map_id

    @pytest.mark.asyncio
    async def test_get_map_id_from_thread_returns_none_for_non_existent_thread(
        self,
        repository: PlaytestRepository,
    ) -> None:
        """Test get_map_id_from_thread returns None when thread doesn't exist."""
        # Arrange
        non_existent_thread_id = 999999999999999999

        # Act
        result = await repository.get_map_id_from_thread(non_existent_thread_id)

        # Assert
        assert result is None


# ==============================================================================
# GET PRIMARY CREATOR TESTS
# ==============================================================================


class TestGetPrimaryCreator:
    """Test getting primary creator for a map."""

    @pytest.mark.asyncio
    async def test_get_primary_creator_returns_user_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test get_primary_creator returns primary creator's user ID."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()

        # Insert creator as primary
        await asyncpg_conn.execute(
            """
            INSERT INTO maps.creators (map_id, user_id, is_primary)
            VALUES ($1, $2, TRUE)
            """,
            map_id,
            user_id,
        )

        # Act
        result = await repository.get_primary_creator(map_id)

        # Assert
        assert result == user_id

    @pytest.mark.asyncio
    async def test_get_primary_creator_returns_none_when_no_creators(
        self,
        repository: PlaytestRepository,
        create_test_map,
    ) -> None:
        """Test get_primary_creator returns None when map has no creators."""
        # Arrange
        map_id = await create_test_map()

        # Act
        result = await repository.get_primary_creator(map_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_primary_creator_returns_none_when_no_primary(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test get_primary_creator returns None when no primary creator marked."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()

        # Insert creator as non-primary
        await asyncpg_conn.execute(
            """
            INSERT INTO maps.creators (map_id, user_id, is_primary)
            VALUES ($1, $2, FALSE)
            """,
            map_id,
            user_id,
        )

        # Act
        result = await repository.get_primary_creator(map_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_primary_creator_returns_first_when_multiple_primaries(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test get_primary_creator returns one user when multiple primaries exist (data integrity issue)."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()

        # Insert two primary creators (shouldn't happen, but test the behavior)
        await asyncpg_conn.execute(
            """
            INSERT INTO maps.creators (map_id, user_id, is_primary)
            VALUES ($1, $2, TRUE), ($1, $3, TRUE)
            """,
            map_id,
            user1_id,
            user2_id,
        )

        # Act
        result = await repository.get_primary_creator(map_id)

        # Assert - should return one of them
        assert result in [user1_id, user2_id]

    @pytest.mark.asyncio
    async def test_get_primary_creator_with_non_existent_map(
        self,
        repository: PlaytestRepository,
    ) -> None:
        """Test get_primary_creator returns None for non-existent map."""
        # Arrange
        non_existent_map_id = 999999

        # Act
        result = await repository.get_primary_creator(non_existent_map_id)

        # Assert
        assert result is None


# ==============================================================================
# GET MAP CODE TESTS
# ==============================================================================


class TestGetMapCode:
    """Test getting map code from map ID."""

    @pytest.mark.asyncio
    async def test_get_map_code_returns_code(
        self,
        repository: PlaytestRepository,
        create_test_map,
        unique_map_code: str,
    ) -> None:
        """Test get_map_code returns correct map code."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)

        # Act
        result = await repository.get_map_code(map_id)

        # Assert
        assert result == unique_map_code

    @pytest.mark.asyncio
    async def test_get_map_code_returns_none_for_non_existent_map(
        self,
        repository: PlaytestRepository,
    ) -> None:
        """Test get_map_code returns None when map doesn't exist."""
        # Arrange
        non_existent_map_id = 999999

        # Act
        result = await repository.get_map_code(non_existent_map_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_map_code_preserves_case(
        self,
        repository: PlaytestRepository,
        create_test_map,
        global_code_tracker: set[str],
    ) -> None:
        """Test get_map_code preserves the exact case of the code."""
        # Arrange
        from uuid import uuid4

        # Create code with mixed case
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)
        map_id = await create_test_map(code=code)

        # Act
        result = await repository.get_map_code(map_id)

        # Assert
        assert result == code
        assert result.isupper()
