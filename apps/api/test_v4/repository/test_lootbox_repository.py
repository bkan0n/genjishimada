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


class TestWriteOperations:
    """Test write operations."""

    async def test_delete_user_key(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test deleting oldest user key."""
        async with db_pool.acquire() as conn:
            # Create test user
            await conn.execute(
                "INSERT INTO core.users (id) VALUES ($1) ON CONFLICT DO NOTHING",
                999,
            )
            # Insert test key
            await conn.execute(
                "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
                999,
                "Classic",
            )
            # Delete it
            await lootbox_repo.delete_oldest_user_key(user_id=999, key_type="Classic", conn=conn)
            # Verify deletion
            count = await conn.fetchval(
                "SELECT count(*) FROM lootbox.user_keys WHERE user_id = $1 AND key_type = $2",
                999,
                "Classic",
            )
            assert count == 0

    async def test_insert_user_reward(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test inserting user reward."""
        async with db_pool.acquire() as conn:
            # Create test user
            await conn.execute(
                "INSERT INTO core.users (id) VALUES ($1) ON CONFLICT DO NOTHING",
                999,
            )
            await lootbox_repo.insert_user_reward(
                user_id=999,
                reward_type="spray",
                key_type="Classic",
                reward_name="God Of War",
                conn=conn,
            )
            # Verify insertion
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM lootbox.user_rewards WHERE user_id = $1 AND reward_name = $2)",
                999,
                "God Of War",
            )
            assert exists

    async def test_add_user_coins(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test adding coins to user."""
        async with db_pool.acquire() as conn:
            await lootbox_repo.add_user_coins(user_id=999, amount=100, conn=conn)
            # Verify coins
            coins = await conn.fetchval("SELECT coins FROM core.users WHERE id = $1", 999)
            assert coins >= 100

    async def test_insert_user_key(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test inserting user key."""
        async with db_pool.acquire() as conn:
            # Create test user
            await conn.execute(
                "INSERT INTO core.users (id) VALUES ($1) ON CONFLICT DO NOTHING",
                999,
            )
            await lootbox_repo.insert_user_key(user_id=999, key_type="Classic", conn=conn)
            # Verify insertion
            count = await conn.fetchval(
                "SELECT count(*) FROM lootbox.user_keys WHERE user_id = $1 AND key_type = $2",
                999,
                "Classic",
            )
            assert count > 0

    async def test_upsert_user_xp(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test upserting user XP."""
        async with db_pool.acquire() as conn:
            # Create test user
            await conn.execute(
                "INSERT INTO core.users (id) VALUES ($1) ON CONFLICT DO NOTHING",
                999,
            )
            result = await lootbox_repo.upsert_user_xp(
                user_id=999,
                xp_amount=50,
                multiplier=1.0,
                conn=conn,
            )
            assert "previous_amount" in result
            assert "new_amount" in result
            assert result["new_amount"] >= 50

    async def test_update_xp_multiplier(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test updating XP multiplier."""
        async with db_pool.acquire() as conn:
            await lootbox_repo.update_xp_multiplier(multiplier=2.0, conn=conn)
            # Verify update
            value = await conn.fetchval("SELECT value FROM lootbox.xp_multiplier LIMIT 1")
            assert value == 2.0

    async def test_update_active_key(self, lootbox_repo: LootboxRepository, db_pool: asyncpg.Pool):
        """Test updating active key."""
        async with db_pool.acquire() as conn:
            await lootbox_repo.update_active_key(key_type="Winter", conn=conn)
            # Verify update
            active = await conn.fetchval("SELECT key FROM lootbox.active_key LIMIT 1")
            assert active == "Winter"
