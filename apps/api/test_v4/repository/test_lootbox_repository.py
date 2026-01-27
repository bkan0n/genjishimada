"""Tests for LootboxRepository."""

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.lootbox_repository import LootboxRepository


@pytest.fixture
async def db_pool(postgres_service: PostgresService):
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
