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
