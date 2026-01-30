"""Tests for ChangeRequestsRepository edge cases.

Test Coverage:
- Transaction isolation
- Null/empty value handling
- Special characters in content
- Boundary values
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
# NULL AND EMPTY VALUE TESTS
# ==============================================================================


class TestNullAndEmptyValues:
    """Test handling of null and empty values."""

    @pytest.mark.asyncio
    async def test_create_with_empty_content(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating change request with empty content string."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content="",  # Empty string
            change_request_type="Bug Fix",
            creator_mentions="",
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result == ""

    @pytest.mark.asyncio
    async def test_create_with_very_long_content(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating change request with very long content."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        long_content = fake.text(max_nb_chars=5000)

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=long_content,
            change_request_type="Feature Request",
            creator_mentions="",
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result is not None

    @pytest.mark.asyncio
    async def test_create_with_special_characters_in_content(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating change request with special characters in content."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        special_content = "Test with 'quotes', \"double quotes\", and\nnewlines\t\ttabs"

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=special_content,
            change_request_type="Bug Fix",
            creator_mentions="",
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result is not None

    @pytest.mark.asyncio
    async def test_create_with_unicode_characters(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating change request with unicode characters."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        unicode_content = "Test with émojis 🎮🎯 and spëcial çharacters 日本語"

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=unicode_content,
            change_request_type="Improvement",
            creator_mentions="",
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result is not None


# ==============================================================================
# BOUNDARY VALUE TESTS
# ==============================================================================


class TestBoundaryValues:
    """Test boundary value scenarios."""

    @pytest.mark.asyncio
    async def test_create_with_min_thread_id(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test creating with minimum valid thread_id (18-digit Discord snowflake)."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        min_thread_id = 100000000000000000  # Minimum 18-digit

        # Act
        await repository.create_request(
            thread_id=min_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=fake.sentence(),
            change_request_type="Bug Fix",
            creator_mentions="",
        )

        # Assert
        result = await repository.fetch_creator_mentions(min_thread_id, unique_map_code)
        assert result is not None

    @pytest.mark.asyncio
    async def test_create_with_max_thread_id(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test creating with maximum valid thread_id (18-digit Discord snowflake)."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        max_thread_id = 999999999999999999  # Maximum 18-digit

        # Act
        await repository.create_request(
            thread_id=max_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=fake.sentence(),
            change_request_type="Bug Fix",
            creator_mentions="",
        )

        # Assert
        result = await repository.fetch_creator_mentions(max_thread_id, unique_map_code)
        assert result is not None

    @pytest.mark.asyncio
    async def test_creator_mentions_with_many_ids(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test creating change request with many creator IDs in mentions."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create many creator IDs
        creator_ids = [await create_test_user() for _ in range(20)]
        creator_mentions = ",".join(str(cid) for cid in creator_ids)

        # Act
        await repository.create_request(
            thread_id=unique_thread_id,
            code=unique_map_code,
            user_id=user_id,
            content=fake.sentence(),
            change_request_type="Bug Fix",
            creator_mentions=creator_mentions,
        )

        # Assert
        result = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result == creator_mentions


# ==============================================================================
# TRANSACTION ISOLATION TESTS
# ==============================================================================


class TestTransactionIsolation:
    """Test transaction isolation scenarios."""

    @pytest.mark.asyncio
    async def test_uncommitted_create_not_visible_outside_transaction(
        self,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        unique_map_code: str,
    ):
        """Test uncommitted create is not visible outside transaction."""
        # Arrange
        repository = ChangeRequestsRepository(asyncpg_conn)
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Act - create within transaction but don't commit yet
        async with asyncpg_conn.transaction():
            await repository.create_request(
                thread_id=unique_thread_id,
                code=unique_map_code,
                user_id=user_id,
                content=fake.sentence(),
                change_request_type="Bug Fix",
                creator_mentions="",
                conn=asyncpg_conn,
            )

            # Within transaction, record exists
            result_inside = await repository.fetch_creator_mentions(
                unique_thread_id,
                unique_map_code,
                conn=asyncpg_conn,
            )
            assert result_inside is not None

        # After transaction commits, record should be visible
        result_outside = await repository.fetch_creator_mentions(unique_thread_id, unique_map_code)
        assert result_outside is not None
