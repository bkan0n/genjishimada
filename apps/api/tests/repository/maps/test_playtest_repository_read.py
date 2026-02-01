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
        user_id = await create_test_user()
        map_id = await create_test_map(creator_id=user_id)

        # Act
        result = await repository.get_primary_creator(map_id)

        # Assert
        assert result == user_id


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
