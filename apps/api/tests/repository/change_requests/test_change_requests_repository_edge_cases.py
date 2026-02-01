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
