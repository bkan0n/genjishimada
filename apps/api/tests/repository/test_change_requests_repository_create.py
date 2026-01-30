"""Tests for ChangeRequestsRepository create operations."""

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


@pytest.mark.asyncio
async def test_fixture_smoke_test(create_test_map, create_test_user, create_test_change_request):
    """Verify that the create_test_change_request fixture works."""
    # Arrange
    map_code = f"T{uuid4().hex[:5].upper()}"
    map_id = await create_test_map(map_code)
    user_id = await create_test_user()

    # Act
    thread_id = await create_test_change_request(map_code, user_id)

    # Assert
    assert isinstance(thread_id, int)
    assert thread_id > 0
