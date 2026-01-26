"""Tests for CompletionsRepository."""

from typing import AsyncGenerator

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.completions_repository import CompletionsRepository


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
async def completions_repo(db_pool: asyncpg.Pool) -> CompletionsRepository:
    """Create completions repository instance."""
    return CompletionsRepository(db_pool)


class TestRepositorySmoke:
    """Smoke tests for repository wiring."""

    async def test_repository_instantiates(self, completions_repo: CompletionsRepository) -> None:
        """Ensure repository can be instantiated."""
        assert completions_repo is not None


class TestRepositoryQueries:
    """Basic query shape tests."""

    async def test_fetch_user_completions_returns_list(self, completions_repo: CompletionsRepository) -> None:
        """Ensure user completions query returns a list."""
        result = await completions_repo.fetch_user_completions(
            user_id=1,
            difficulty=None,
            page_size=10,
            page_number=1,
        )
        assert isinstance(result, list)

    async def test_fetch_map_leaderboard_returns_list(self, completions_repo: CompletionsRepository) -> None:
        """Ensure map leaderboard query returns a list."""
        result = await completions_repo.fetch_map_leaderboard(
            code="1EASY",
            page_size=10,
            page_number=1,
        )
        assert isinstance(result, list)

    async def test_fetch_pending_verifications_returns_list(self, completions_repo: CompletionsRepository) -> None:
        """Ensure pending verifications query returns a list."""
        result = await completions_repo.fetch_pending_verifications()
        assert isinstance(result, list)
