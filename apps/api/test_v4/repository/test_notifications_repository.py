"""Tests for NotificationsRepository."""

import datetime as dt

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.notifications_repository import NotificationsRepository


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
async def notifications_repo(db_pool: asyncpg.Pool) -> NotificationsRepository:
    """Create repository instance."""
    return NotificationsRepository(db_pool)


class TestNotificationsQueries:
    """Test repository methods."""

    async def test_insert_event_returns_id(self, notifications_repo: NotificationsRepository):
        """Test that inserting event returns new ID."""
        result = await notifications_repo.insert_event(
            user_id=300,
            event_type="xp_gain",
            title="XP Gained",
            body="You gained 100 XP",
            metadata={"xp_amount": 100},
        )
        assert isinstance(result, int)
        assert result > 0

    async def test_fetch_user_events_returns_list(self, notifications_repo: NotificationsRepository):
        """Test fetching user events returns list."""
        result = await notifications_repo.fetch_user_events(
            user_id=300,
            unread_only=False,
            limit=50,
            offset=0,
        )
        assert isinstance(result, list)

    async def test_fetch_unread_count_returns_int(self, notifications_repo: NotificationsRepository):
        """Test fetching unread count returns integer."""
        result = await notifications_repo.fetch_unread_count(user_id=300)
        assert isinstance(result, int)

    async def test_mark_event_read(self, notifications_repo: NotificationsRepository):
        """Test marking event as read."""
        # Insert test event first
        event_id = await notifications_repo.insert_event(
            user_id=300,
            event_type="xp_gain",
            title="Test",
            body="Test",
            metadata=None,
        )
        await notifications_repo.mark_event_read(event_id)
        # No error means success

    async def test_fetch_preferences_returns_list(self, notifications_repo: NotificationsRepository):
        """Test fetching preferences returns list."""
        result = await notifications_repo.fetch_preferences(user_id=300)
        assert isinstance(result, list)

    async def test_upsert_preference(self, notifications_repo: NotificationsRepository):
        """Test upserting a preference."""
        await notifications_repo.upsert_preference(
            user_id=300,
            event_type="xp_gain",
            channel="discord_dm",
            enabled=True,
        )
        # No error means success
