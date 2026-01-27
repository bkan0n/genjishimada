"""Tests for NewsfeedRepository."""

import datetime as dt
from typing import AsyncGenerator

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.newsfeed_repository import NewsfeedRepository


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
    yield pool
    await pool.close()


@pytest.fixture
async def newsfeed_repo(db_pool: asyncpg.Pool) -> NewsfeedRepository:
    """Create repository instance."""
    return NewsfeedRepository(db_pool)


class TestNewsfeedQueries:
    """Test repository methods."""

    async def test_insert_event_returns_id(self, newsfeed_repo: NewsfeedRepository):
        """Test that inserting event returns new ID."""
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {"type": "announcement", "title": "Test", "content": "Test content"}
        result = await newsfeed_repo.insert_event(timestamp, payload)
        assert isinstance(result, int)
        assert result > 0

    async def test_fetch_event_by_id_returns_dict(self, newsfeed_repo: NewsfeedRepository):
        """Test fetching event by ID returns dict."""
        # Insert test event first
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {"type": "guide", "code": "TEST1", "guide_url": "https://example.com", "name": "Tester"}
        event_id = await newsfeed_repo.insert_event(timestamp, payload)

        # Fetch it back
        result = await newsfeed_repo.fetch_event_by_id(event_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["id"] == event_id

    async def test_fetch_events_returns_list(self, newsfeed_repo: NewsfeedRepository):
        """Test fetching events returns list."""
        result = await newsfeed_repo.fetch_events(limit=10, offset=0, event_type=None)
        assert isinstance(result, list)
