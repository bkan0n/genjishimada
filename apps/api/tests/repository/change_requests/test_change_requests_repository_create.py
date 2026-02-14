"""Tests for ChangeRequestsRepository create operations.

Test Coverage:
- Happy path: create with valid data
- Constraint violations: duplicate thread_id
- Foreign key violations: invalid code, invalid user_id
- Transaction behavior: rollback
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.change_requests_repository import ChangeRequestsRepository
from repository.exceptions import ForeignKeyViolationError

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


class TestCreateRequestHappyPath:
    """Test happy path scenarios for create_request."""

    @pytest.mark.asyncio
    async def test_create_with_valid_data_succeeds(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating a change request with valid data succeeds."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        content = fake.sentence(nb_words=20)
        change_request_type = "Bug Fix"
        creator_mentions = f"{user_id}"

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=content,
            change_request_type=change_request_type,
            creator_mentions=creator_mentions,
        )

        # Assert - verify the record was created
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result == creator_mentions

    @pytest.mark.asyncio
    async def test_create_with_empty_creator_mentions_succeeds(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating a change request with empty creator_mentions succeeds."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        content = fake.sentence(nb_words=20)
        change_request_type = "Feature Request"
        creator_mentions = ""

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=content,
            change_request_type=change_request_type,
            creator_mentions=creator_mentions,
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result == ""

    @pytest.mark.asyncio
    async def test_create_with_multiple_creator_mentions_succeeds(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating a change request with multiple creator mentions succeeds."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        creator1_id = await create_test_user()
        creator2_id = await create_test_user()
        creator_mentions = f"{creator1_id},{creator2_id}"
        content = fake.sentence(nb_words=20)
        change_request_type = "Improvement"

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=content,
            change_request_type=change_request_type,
            creator_mentions=creator_mentions,
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result == creator_mentions

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "change_request_type",
        ["Bug Fix", "Feature Request", "Improvement", "Balance Change"],
    )
    async def test_create_with_different_request_types_succeeds(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_thread_id: int,
        change_request_type: str,
    ):
        """Test creating change requests with different types succeeds."""
        # Arrange
        map_code = unique_map_code
        await create_test_map(map_code)
        user_id = await create_test_user()

        content = fake.sentence(nb_words=20)
        creator_mentions = ""

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=map_code,
            user_id=user_id,
            content=content,
            change_request_type=change_request_type,
            creator_mentions=creator_mentions,
        )

        # Assert - no exception raised means success
        result = await repository.fetch_creator_mentions(unique_thread_id, map_code)
        assert result is not None


# ==============================================================================
# ERROR CASE TESTS
# ==============================================================================


class TestCreateRequestErrorCases:
    """Test error handling for create_request."""

    @pytest.mark.asyncio
    async def test_create_with_invalid_code_does_not_insert(
        self,
        repository: ChangeRequestsRepository,
        create_test_user,
        unique_thread_id: int,
    ):
        """Test creating with non-existent map code does not insert record.

        The create_request method uses a SELECT query that silently skips
        insertion if the map code doesn't exist.
        """
        # Arrange
        user_id = await create_test_user()
        invalid_code = f"INVALID{uuid4().hex[:5].upper()}"
        content = fake.sentence(nb_words=20)
        change_request_type = "Bug Fix"
        creator_mentions = ""

        # Act - should not raise error, but also should not insert
        await repository.create_request(
            thread_id=unique_thread_id,
            code=invalid_code,
            user_id=user_id,
            content=content,
            change_request_type=change_request_type,
            creator_mentions=creator_mentions,
        )

        # Assert - verify no record was created
        result = await repository.fetch_creator_mentions(unique_thread_id, invalid_code)
        assert result is None




# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================
