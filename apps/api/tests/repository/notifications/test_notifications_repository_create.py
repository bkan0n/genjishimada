"""Tests for NotificationsRepository create operations."""

import json
from uuid import uuid4

import pytest
from faker import Faker

from repository.exceptions import ForeignKeyViolationError
from repository.notifications_repository import NotificationsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_notifications,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide notifications repository instance."""
    return NotificationsRepository(asyncpg_conn)


# ==============================================================================
# insert_event TESTS
# ==============================================================================


class TestInsertEventHappyPath:
    """Test happy path scenarios for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_with_valid_data_returns_id(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with valid data returns event ID."""
        # Arrange
        user_id = await create_test_user()
        event_type = fake.word()
        title = fake.sentence(nb_words=5)
        body = fake.sentence(nb_words=15)

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type=event_type,
            title=title,
            body=body,
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

        # Verify in database
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row is not None
        assert row["user_id"] == user_id
        assert row["event_type"] == event_type
        assert row["title"] == title
        assert row["body"] == body
        assert row["metadata"] is None
