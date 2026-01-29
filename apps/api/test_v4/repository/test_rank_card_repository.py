"""Tests for RankCardRepository."""

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.rank_card_repository import RankCardRepository


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
async def rank_card_repo(db_pool: asyncpg.Pool) -> RankCardRepository:
    """Create repository instance."""
    return RankCardRepository(db_pool)


class TestRankCardQueries:
    """Test repository methods."""

    async def test_fetch_background_returns_dict(self, rank_card_repo: RankCardRepository):
        """Test that query returns expected type."""
        result = await rank_card_repo.fetch_background(user_id=1)
        assert isinstance(result, dict) or result is None

    async def test_fetch_background_with_user(self, rank_card_repo: RankCardRepository, db_pool: asyncpg.Pool):
        """Test fetching background for existing user."""
        # Insert test data
        async with db_pool.acquire() as conn:
            user_id = 12345
            await conn.execute("INSERT INTO core.users (id, nickname) VALUES ($1, $2)", user_id, "testuser")
            await conn.execute("INSERT INTO rank_card.background (user_id, name) VALUES ($1, $2)", user_id, "test_bg")

        result = await rank_card_repo.fetch_background(user_id=user_id)
        assert result is not None
        assert result["name"] == "test_bg"
