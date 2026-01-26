"""Tests for ChangeRequestsRepository."""

from typing import AsyncGenerator

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.change_requests_repository import ChangeRequestsRepository


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
async def change_requests_repo(db_pool: asyncpg.Pool) -> ChangeRequestsRepository:
    """Create change requests repository instance."""
    return ChangeRequestsRepository(db_pool)


class TestPermissionCheck:
    """Test permission check query."""

    async def test_fetch_creator_mentions_returns_string_or_none(
        self, change_requests_repo: ChangeRequestsRepository
    ) -> None:
        """Test that creator mentions query returns string or None."""
        result = await change_requests_repo.fetch_creator_mentions(
            thread_id=1000000001,
            code="1EASY",
        )
        # May be None or string, both valid
        assert result is None or isinstance(result, str)


class TestListRequests:
    """Test list queries."""

    async def test_fetch_unresolved_requests_returns_list(
        self, change_requests_repo: ChangeRequestsRepository
    ) -> None:
        """Test that unresolved requests query returns list."""
        result = await change_requests_repo.fetch_unresolved_requests(code="1EASY")
        assert isinstance(result, list)

    async def test_fetch_stale_requests_returns_list(
        self, change_requests_repo: ChangeRequestsRepository
    ) -> None:
        """Test that stale requests query returns list."""
        result = await change_requests_repo.fetch_stale_requests()
        assert isinstance(result, list)
