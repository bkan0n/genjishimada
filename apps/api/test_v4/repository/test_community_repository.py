"""Tests for CommunityRepository."""

from typing import AsyncGenerator

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.community_repository import CommunityRepository


@pytest.fixture
async def db_pool(postgres_service: PostgresService) -> AsyncGenerator[asyncpg.Pool, None]:
    """Create asyncpg pool for tests."""
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    if pool is None:
        msg = "Failed to create database pool"
        raise RuntimeError(msg)
    yield pool
    await pool.close()


@pytest.fixture
async def community_repo(db_pool: asyncpg.Pool) -> CommunityRepository:
    """Create community repository instance."""
    return CommunityRepository(db_pool)


class TestLeaderboard:
    """Test leaderboard query methods."""

    async def test_get_community_leaderboard_returns_list(self, community_repo: CommunityRepository) -> None:
        """Test that leaderboard query returns a list."""
        result = await community_repo.fetch_community_leaderboard(
            name=None,
            tier_name=None,
            skill_rank=None,
            sort_column="xp_amount",
            sort_direction="desc",
            page_size=10,
            page_number=1,
        )
        assert isinstance(result, list)
        assert len(result) <= 10
