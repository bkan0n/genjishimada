"""Tests for LootboxRepository create operations (inserts)."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.lootbox_repository import LootboxRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_lootbox,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide lootbox repository instance."""
    return LootboxRepository(asyncpg_conn)

# Tests will go here
