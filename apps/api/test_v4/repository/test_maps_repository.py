"""Tests for MapsRepository."""

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
async def maps_repo(db_pool: asyncpg.Pool):
    """Create repository instance."""
    from repository.maps_repository import MapsRepository

    return MapsRepository(db_pool)


class TestMapsRepositoryBasic:
    """Test basic repository functionality."""

    async def test_repository_instantiates(self, maps_repo):
        """Test that repository can be instantiated."""
        assert maps_repo is not None
        assert hasattr(maps_repo, "_pool")
