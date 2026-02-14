"""Tests for LootboxRepository coin helpers."""

import pytest

from repository.lootbox_repository import LootboxRepository

pytestmark = [
    pytest.mark.domain_lootbox,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide lootbox repository instance."""
    return LootboxRepository(asyncpg_conn)


class TestDeductUserCoins:
    """Tests for deduct_user_coins."""

    async def test_deduct_user_coins_success(self, repository, create_test_user, asyncpg_conn):
        user_id = await create_test_user()
        await asyncpg_conn.execute("UPDATE core.users SET coins = 1000 WHERE id = $1", user_id)

        new_balance = await repository.deduct_user_coins(user_id, 500)

        assert new_balance == 500

    async def test_deduct_user_coins_insufficient(self, repository, create_test_user, asyncpg_conn):
        user_id = await create_test_user()
        await asyncpg_conn.execute("UPDATE core.users SET coins = 200 WHERE id = $1", user_id)

        new_balance = await repository.deduct_user_coins(user_id, 500)

        assert new_balance is None
