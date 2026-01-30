"""Tests for RankCardRepository read operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.rank_card_repository import RankCardRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_rank_card,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide rank_card repository instance."""
    return RankCardRepository(asyncpg_conn)

# Tests will go here
