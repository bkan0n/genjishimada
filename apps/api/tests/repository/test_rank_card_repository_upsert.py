"""Tests for RankCardRepository upsert operations."""

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


# ==============================================================================
# VERIFICATION TEST - Remove after confirming fixtures work
# ==============================================================================


async def test_unique_user_id_fixture_works(unique_user_id: int) -> None:
    """Verify unique_user_id fixture generates valid Discord snowflakes."""
    assert isinstance(unique_user_id, int)
    assert 100000000000000000 <= unique_user_id <= 999999999999999999  # 18-digit range
    assert len(str(unique_user_id)) == 18


async def test_create_test_user_fixture_works(create_test_user) -> None:
    """Verify create_test_user factory fixture works."""
    user_id = await create_test_user()
    assert isinstance(user_id, int)
    assert user_id > 0

