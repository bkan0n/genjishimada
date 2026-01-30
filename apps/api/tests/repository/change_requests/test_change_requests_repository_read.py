"""Tests for ChangeRequestsRepository read operations.

Test Coverage:
- Happy path: fetch existing creator_mentions
- Not found: non-existent thread_id returns None
- Not found: non-existent code returns None
- Edge case: empty creator_mentions
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.change_requests_repository import ChangeRequestsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_change_requests,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide change_requests repository instance."""
    return ChangeRequestsRepository(asyncpg_conn)


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestFetchCreatorMentionsHappyPath:
    """Test happy path scenarios for fetch_creator_mentions."""

    @pytest.mark.asyncio
    async def test_fetch_existing_creator_mentions_returns_value(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching existing creator_mentions returns correct value."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        creator1_id = await create_test_user()
        creator2_id = await create_test_user()
        expected_mentions = f"{creator1_id},{creator2_id}"

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            creator_mentions=expected_mentions,
        )

        # Act
        result = await repository.fetch_creator_mentions(thread_id, unique_map_code)

        # Assert
        assert result == expected_mentions

    @pytest.mark.asyncio
    async def test_fetch_empty_creator_mentions_returns_empty_string(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching empty creator_mentions returns empty string."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            creator_mentions="",
        )

        # Act
        result = await repository.fetch_creator_mentions(thread_id, unique_map_code)

        # Assert
        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_with_multiple_change_requests_returns_correct_one(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
    ):
        """Test fetching creator_mentions returns correct value when multiple exist."""
        # Arrange - create multiple change requests
        map_code1 = f"T{uuid4().hex[:5].upper()}"
        map_code2 = f"T{uuid4().hex[:5].upper()}"

        map_id1 = await create_test_map(map_code1)
        map_id2 = await create_test_map(map_code2)

        user_id = await create_test_user()
        creator1_id = await create_test_user()
        creator2_id = await create_test_user()

        mentions1 = f"{creator1_id}"
        mentions2 = f"{creator2_id}"

        thread_id1 = await create_test_change_request(
            code=map_code1,
            user_id=user_id,
            creator_mentions=mentions1,
        )

        thread_id2 = await create_test_change_request(
            code=map_code2,
            user_id=user_id,
            creator_mentions=mentions2,
        )

        # Act & Assert - fetch first one
        result1 = await repository.fetch_creator_mentions(thread_id1, map_code1)
        assert result1 == mentions1

        # Act & Assert - fetch second one
        result2 = await repository.fetch_creator_mentions(thread_id2, map_code2)
        assert result2 == mentions2


# ==============================================================================
# NOT FOUND TESTS
# ==============================================================================


class TestFetchCreatorMentionsNotFound:
    """Test not found scenarios for fetch_creator_mentions."""

    @pytest.mark.asyncio
    async def test_fetch_nonexistent_thread_id_returns_none(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        unique_map_code: str,
    ):
        """Test fetching with non-existent thread_id returns None."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        nonexistent_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)

        # Act
        result = await repository.fetch_creator_mentions(nonexistent_thread_id, unique_map_code)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_nonexistent_code_returns_none(
        self,
        repository: ChangeRequestsRepository,
        unique_thread_id: int,
    ):
        """Test fetching with non-existent code returns None."""
        # Arrange
        nonexistent_code = f"INVALID{uuid4().hex[:5].upper()}"

        # Act
        result = await repository.fetch_creator_mentions(unique_thread_id, nonexistent_code)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_wrong_thread_code_combination_returns_none(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
    ):
        """Test fetching with wrong thread_id/code combination returns None."""
        # Arrange
        map_code1 = f"T{uuid4().hex[:5].upper()}"
        map_code2 = f"T{uuid4().hex[:5].upper()}"

        map_id1 = await create_test_map(map_code1)
        map_id2 = await create_test_map(map_code2)

        user_id = await create_test_user()

        # Create change request for map_code1
        thread_id = await create_test_change_request(
            code=map_code1,
            user_id=user_id,
            creator_mentions="123456",
        )

        # Act - try to fetch with correct thread_id but wrong code
        result = await repository.fetch_creator_mentions(thread_id, map_code2)

        # Assert
        assert result is None
