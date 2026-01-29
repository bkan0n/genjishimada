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
