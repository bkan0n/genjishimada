"""Tests for UsersRepository create operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.users_repository import UsersRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_users,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide users repository instance."""
    return UsersRepository(asyncpg_conn)


def test_unique_user_id_fixture(unique_user_id: int):
    """Verify unique user ID generation works."""
    assert isinstance(unique_user_id, int)
    assert 100000000000000000 <= unique_user_id <= 999999999999999999
    assert len(str(unique_user_id)) == 18
