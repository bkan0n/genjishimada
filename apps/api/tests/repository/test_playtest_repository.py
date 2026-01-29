"""Tests for PlaytestRepository."""

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService


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
async def playtest_repo(db_pool: asyncpg.Pool):
    """Create repository instance."""
    from repository.playtest_repository import PlaytestRepository

    return PlaytestRepository(db_pool)


class TestPlaytestRepositoryBasic:
    """Test basic repository functionality."""

    @pytest.mark.asyncio
    async def test_repository_instantiates(self, playtest_repo):
        """Test that repository can be instantiated."""
        assert playtest_repo is not None
