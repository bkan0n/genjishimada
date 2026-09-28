"""Tests for MapsRepository."""

import asyncpg
import pytest

pytestmark = [pytest.mark.database]


@pytest.fixture
async def db_pool(asyncpg_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Reuse the isolated, fixture-owned pool."""
    return asyncpg_pool


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
