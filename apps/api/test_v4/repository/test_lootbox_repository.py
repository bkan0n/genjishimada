"""Tests for LootboxRepository."""

from collections.abc import AsyncGenerator

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.lootbox_repository import LootboxRepository


@pytest.fixture
async def db_pool(postgres_service: PostgresService) -> AsyncGenerator[asyncpg.Pool]:
    """Create asyncpg pool for tests."""
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def lootbox_repo(db_pool: asyncpg.Pool) -> LootboxRepository:
    """Create repository instance."""
    return LootboxRepository(db_pool)


class TestLootboxQueries:
    """Test repository query methods."""

    async def test_fetch_all_rewards_returns_list(self, lootbox_repo: LootboxRepository):
        """Test that fetch_all_rewards returns a list."""
        result = await lootbox_repo.fetch_all_rewards()
        assert isinstance(result, list)

    async def test_fetch_all_key_types_returns_list(self, lootbox_repo: LootboxRepository):
        """Test that fetch_all_key_types returns a list."""
        result = await lootbox_repo.fetch_all_key_types()
        assert isinstance(result, list)


class TestRewardQueries:
    """Test reward query methods."""

    async def test_fetch_all_rewards_with_filters(self, lootbox_repo: LootboxRepository):
        """Test rewards query with optional filters."""
        result = await lootbox_repo.fetch_all_rewards(
            reward_type="spray",
            key_type="Classic",
            rarity="common"
        )
        assert isinstance(result, list)

    async def test_fetch_user_rewards(self, lootbox_repo: LootboxRepository):
        """Test user rewards query."""
        result = await lootbox_repo.fetch_user_rewards(user_id=1)
        assert isinstance(result, list)


class TestKeyQueries:
    """Test key query methods."""

    async def test_fetch_all_key_types_with_filter(self, lootbox_repo: LootboxRepository):
        """Test key types query with filter."""
        result = await lootbox_repo.fetch_all_key_types(key_type="Classic")
        assert isinstance(result, list)

    async def test_fetch_user_keys(self, lootbox_repo: LootboxRepository):
        """Test user keys query."""
        result = await lootbox_repo.fetch_user_keys(user_id=1)
        assert isinstance(result, list)

    async def test_fetch_user_key_count(self, lootbox_repo: LootboxRepository):
        """Test user key count query."""
        count = await lootbox_repo.fetch_user_key_count(user_id=1, key_type="Classic")
        assert isinstance(count, int)
        assert count >= 0


class TestUserQueries:
    """Test user-related query methods."""

    async def test_fetch_user_coins(self, lootbox_repo: LootboxRepository):
        """Test user coins query."""
        coins = await lootbox_repo.fetch_user_coins(user_id=1)
        assert isinstance(coins, int)
        assert coins >= 0


class TestXpQueries:
    """Test XP-related query methods."""

    async def test_fetch_xp_tier_change(self, lootbox_repo: LootboxRepository):
        """Test XP tier change calculation."""
        result = await lootbox_repo.fetch_xp_tier_change(old_xp=0, new_xp=100)
        assert isinstance(result, dict)

    async def test_fetch_xp_multiplier(self, lootbox_repo: LootboxRepository):
        """Test XP multiplier query."""
        multiplier = await lootbox_repo.fetch_xp_multiplier()
        assert isinstance(multiplier, (float, int)) or hasattr(multiplier, '__float__')
        assert float(multiplier) > 0
