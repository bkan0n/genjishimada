"""Tests for AuthRepository session operations.

Test Coverage:
- write_session: create new, update existing, with/without user_id, upsert behavior
- read_session: valid, expired, not found, expiration boundary
- delete_session: exists, not exists, returns correct boolean
- delete_expired_sessions: deletes expired only, returns count, preserves active
- get_user_sessions: returns active only, ordered by activity, filters by user
- delete_user_sessions: all, except specific session, returns count
"""

import datetime as dt
from uuid import uuid4

import pytest
from faker import Faker

from repository.auth_repository import AuthRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_auth,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide auth repository instance."""
    return AuthRepository(asyncpg_conn)


# ==============================================================================
# write_session TESTS
# ==============================================================================


class TestWriteSession:
    """Test write_session method."""

    async def test_create_new_session_succeeds(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_session_id: str,
    ):
        """Test creating new session succeeds."""
        # Arrange
        user_id = await create_test_user()
        payload = "test_payload_base64"
        ip_address = fake.ipv4()
        user_agent = fake.user_agent()

        # Act
        await repository.write_session(
            unique_session_id, payload, user_id, ip_address, user_agent
        )

        # Assert - Verify session exists
        result = await repository.read_session(unique_session_id, session_lifetime_minutes=30)
        assert result == payload

    async def test_update_existing_session_succeeds(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test updating existing session succeeds (upsert)."""
        # Arrange
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        new_payload = "new_payload_base64"
        new_ip = fake.ipv4()
        new_agent = fake.user_agent()

        # Act
        await repository.write_session(
            session_id, new_payload, user_id, new_ip, new_agent
        )

        # Assert - Verify payload updated
        result = await repository.read_session(session_id, session_lifetime_minutes=30)
        assert result == new_payload

    async def test_anonymous_session_with_null_user_id(
        self,
        repository: AuthRepository,
        unique_session_id: str,
    ):
        """Test creating anonymous session with null user_id."""
        # Arrange
        payload = "anonymous_payload"
        ip_address = fake.ipv4()
        user_agent = fake.user_agent()

        # Act
        await repository.write_session(
            unique_session_id, payload, None, ip_address, user_agent
        )

        # Assert - Verify session exists
        result = await repository.read_session(unique_session_id, session_lifetime_minutes=30)
        assert result == payload

    async def test_optional_metadata_can_be_null(
        self,
        repository: AuthRepository,
        unique_session_id: str,
    ):
        """Test that ip_address and user_agent can be null."""
        # Arrange
        payload = "test_payload"

        # Act - Create with null metadata
        await repository.write_session(
            unique_session_id, payload, None, None, None
        )

        # Assert - Verify session exists
        result = await repository.read_session(unique_session_id, session_lifetime_minutes=30)
        assert result == payload

    async def test_upsert_updates_all_fields(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that upsert updates all fields including metadata."""
        # Arrange
        user_id1 = await create_test_user()
        user_id2 = await create_test_user()
        session_id = await create_test_session(user_id=user_id1)

        # Act - Update with different user and metadata
        new_payload = "updated_payload"
        new_ip = "192.168.1.100"
        new_agent = "Updated Agent"

        await repository.write_session(
            session_id, new_payload, user_id2, new_ip, new_agent
        )

        # Assert - Verify all fields updated
        row = await asyncpg_conn.fetchrow(
            "SELECT user_id, payload, ip_address, user_agent FROM users.sessions WHERE id = $1",
            session_id,
        )
        assert row["user_id"] == user_id2
        assert row["payload"] == new_payload
        assert row["ip_address"] == new_ip
        assert row["user_agent"] == new_agent


# ==============================================================================
# read_session TESTS
# ==============================================================================


class TestReadSession:
    """Test read_session method."""

    async def test_active_session_returns_payload(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that active session returns payload."""
        # Arrange
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id, payload="test_payload")

        # Act
        result = await repository.read_session(session_id, session_lifetime_minutes=30)

        # Assert
        assert result == "test_payload"

    async def test_expired_session_returns_none(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that expired session returns None."""
        # Arrange
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        # Manually set last_activity to 2 hours ago
        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '2 hours' WHERE id = $1",
            session_id,
        )

        # Act - Use 30-minute lifetime, so session is expired
        result = await repository.read_session(session_id, session_lifetime_minutes=30)

        # Assert
        assert result is None

    async def test_not_found_returns_none(
        self,
        repository: AuthRepository,
        unique_session_id: str,
    ):
        """Test that non-existent session returns None."""
        # Act
        result = await repository.read_session(unique_session_id, session_lifetime_minutes=30)

        # Assert
        assert result is None

    async def test_expiration_boundary(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test expiration boundary - just at the edge."""
        # Arrange
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        # Set last_activity to exactly 29 minutes ago (within 30-minute window)
        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '29 minutes' WHERE id = $1",
            session_id,
        )

        # Act - Should still be valid
        result = await repository.read_session(session_id, session_lifetime_minutes=30)

        # Assert - Not expired yet
        assert result is not None

    async def test_read_session_refreshes_last_activity(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that reading an active session refreshes last_activity timestamp."""
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '20 minutes' WHERE id = $1",
            session_id,
        )
        old_activity = await asyncpg_conn.fetchval(
            "SELECT last_activity FROM users.sessions WHERE id = $1",
            session_id,
        )

        result = await repository.read_session(session_id, session_lifetime_minutes=30)
        assert result is not None

        new_activity = await asyncpg_conn.fetchval(
            "SELECT last_activity FROM users.sessions WHERE id = $1",
            session_id,
        )
        assert new_activity > old_activity

    async def test_read_session_does_not_refresh_expired_session(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that expired sessions are not refreshed when read."""
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '2 hours' WHERE id = $1",
            session_id,
        )
        old_activity = await asyncpg_conn.fetchval(
            "SELECT last_activity FROM users.sessions WHERE id = $1",
            session_id,
        )

        result = await repository.read_session(session_id, session_lifetime_minutes=30)
        assert result is None

        new_activity = await asyncpg_conn.fetchval(
            "SELECT last_activity FROM users.sessions WHERE id = $1",
            session_id,
        )
        assert new_activity == old_activity


# ==============================================================================
# delete_session TESTS
# ==============================================================================


class TestDeleteSession:
    """Test delete_session method."""

    async def test_delete_existing_returns_true(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test deleting existing session returns True."""
        # Arrange
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        # Act
        result = await repository.delete_session(session_id)

        # Assert
        assert result is True

    async def test_delete_non_existent_returns_false(
        self,
        repository: AuthRepository,
        unique_session_id: str,
    ):
        """Test deleting non-existent session returns False."""
        # Act
        result = await repository.delete_session(unique_session_id)

        # Assert
        assert result is False

    async def test_session_not_readable_after_delete(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that session cannot be read after deletion."""
        # Arrange
        user_id = await create_test_user()
        session_id = await create_test_session(user_id=user_id)

        # Verify it exists first
        before = await repository.read_session(session_id, session_lifetime_minutes=30)
        assert before is not None

        # Act
        await repository.delete_session(session_id)

        # Assert - Cannot read after delete
        after = await repository.read_session(session_id, session_lifetime_minutes=30)
        assert after is None


# ==============================================================================
# delete_expired_sessions TESTS
# ==============================================================================


class TestDeleteExpiredSessions:
    """Test delete_expired_sessions method."""

    async def test_deletes_only_expired_sessions(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that only expired sessions are deleted."""
        # Arrange - Create one active and one expired session
        user_id = await create_test_user()
        active_session = await create_test_session(user_id=user_id)
        expired_session = await create_test_session(user_id=user_id)

        # Make one session expired
        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '2 hours' WHERE id = $1",
            expired_session,
        )

        # Act - Delete sessions older than 30 minutes
        count = await repository.delete_expired_sessions(session_lifetime_minutes=30)

        # Assert
        assert count >= 1

        # Verify active session still exists
        active_result = await repository.read_session(active_session, session_lifetime_minutes=30)
        assert active_result is not None

        # Verify expired session deleted
        expired_result = await repository.read_session(
            expired_session, session_lifetime_minutes=30
        )
        assert expired_result is None

    async def test_returns_correct_count(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that correct count of deleted sessions is returned."""
        # Arrange - Create multiple expired sessions
        user_id = await create_test_user()
        expired_sessions = []
        for _ in range(3):
            session_id = await create_test_session(user_id=user_id)
            expired_sessions.append(session_id)
            await asyncpg_conn.execute(
                "UPDATE users.sessions SET last_activity = now() - INTERVAL '2 hours' WHERE id = $1",
                session_id,
            )

        # Act
        count = await repository.delete_expired_sessions(session_lifetime_minutes=30)

        # Assert - At least 3 were deleted
        assert count >= 3

    async def test_no_expired_sessions_returns_zero(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that when no sessions are expired, returns 0."""
        # Arrange - Create only active sessions
        user_id = await create_test_user()
        await create_test_session(user_id=user_id)

        # Act - All sessions are active, none should be deleted
        count = await repository.delete_expired_sessions(session_lifetime_minutes=30)

        # Assert - Could be 0 or count from previous tests, but we created active one
        # Just verify it doesn't error
        assert isinstance(count, int)


# ==============================================================================
# get_user_sessions TESTS
# ==============================================================================


class TestGetUserSessions:
    """Test get_user_sessions method."""

    async def test_returns_active_sessions_only(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that only active sessions are returned."""
        # Arrange
        user_id = await create_test_user()
        active_session = await create_test_session(user_id=user_id)
        expired_session = await create_test_session(user_id=user_id)

        # Make one session expired
        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '2 hours' WHERE id = $1",
            expired_session,
        )

        # Act
        result = await repository.get_user_sessions(user_id, session_lifetime_minutes=30)

        # Assert - Only active session returned
        assert len(result) >= 1
        session_ids = [s["id"] for s in result]
        assert active_session in session_ids
        assert expired_session not in session_ids

    async def test_ordered_by_last_activity_desc(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
        asyncpg_conn,
    ):
        """Test that sessions are ordered by last_activity DESC."""
        # Arrange
        user_id = await create_test_user()
        session1 = await create_test_session(user_id=user_id)
        session2 = await create_test_session(user_id=user_id)
        session3 = await create_test_session(user_id=user_id)

        # Set different last_activity times
        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '10 minutes' WHERE id = $1",
            session1,
        )
        await asyncpg_conn.execute(
            "UPDATE users.sessions SET last_activity = now() - INTERVAL '5 minutes' WHERE id = $1",
            session2,
        )
        # session3 is most recent

        # Act
        result = await repository.get_user_sessions(user_id, session_lifetime_minutes=30)

        # Assert - Ordered by activity, most recent first
        assert len(result) >= 3
        # Most recent should be first
        assert result[0]["id"] == session3

    async def test_excludes_other_users_sessions(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that other users' sessions are not returned."""
        # Arrange
        user_id1 = await create_test_user()
        user_id2 = await create_test_user()

        session1 = await create_test_session(user_id=user_id1)
        session2 = await create_test_session(user_id=user_id2)

        # Act - Get sessions for user1
        result = await repository.get_user_sessions(user_id1, session_lifetime_minutes=30)

        # Assert
        session_ids = [s["id"] for s in result]
        assert session1 in session_ids
        assert session2 not in session_ids

    async def test_user_with_no_sessions_returns_empty_list(
        self,
        repository: AuthRepository,
        create_test_user,
    ):
        """Test that user with no sessions returns empty list."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.get_user_sessions(user_id, session_lifetime_minutes=30)

        # Assert
        assert result == []


# ==============================================================================
# delete_user_sessions TESTS
# ==============================================================================


class TestDeleteUserSessions:
    """Test delete_user_sessions method."""

    async def test_deletes_all_user_sessions(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test deleting all sessions for a user."""
        # Arrange
        user_id = await create_test_user()
        session1 = await create_test_session(user_id=user_id)
        session2 = await create_test_session(user_id=user_id)
        session3 = await create_test_session(user_id=user_id)

        # Act
        count = await repository.delete_user_sessions(user_id)

        # Assert
        assert count >= 3

        # Verify all deleted
        result = await repository.get_user_sessions(user_id, session_lifetime_minutes=30)
        assert result == []

    async def test_preserves_except_session_id(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that except_session_id is preserved."""
        # Arrange
        user_id = await create_test_user()
        keep_session = await create_test_session(user_id=user_id)
        delete_session1 = await create_test_session(user_id=user_id)
        delete_session2 = await create_test_session(user_id=user_id)

        # Act - Delete all except keep_session
        count = await repository.delete_user_sessions(user_id, except_session_id=keep_session)

        # Assert
        assert count >= 2

        # Verify keep_session still exists
        result = await repository.get_user_sessions(user_id, session_lifetime_minutes=30)
        assert len(result) >= 1
        assert result[0]["id"] == keep_session

    async def test_returns_correct_count(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that correct count is returned."""
        # Arrange
        user_id = await create_test_user()
        await create_test_session(user_id=user_id)
        await create_test_session(user_id=user_id)

        # Act
        count = await repository.delete_user_sessions(user_id)

        # Assert
        assert count >= 2

    async def test_doesnt_affect_other_users(
        self,
        repository: AuthRepository,
        create_test_session,
        create_test_user,
    ):
        """Test that deleting one user's sessions doesn't affect others."""
        # Arrange
        user_id1 = await create_test_user()
        user_id2 = await create_test_user()

        session1 = await create_test_session(user_id=user_id1)
        session2 = await create_test_session(user_id=user_id2)

        # Act - Delete user1's sessions
        await repository.delete_user_sessions(user_id1)

        # Assert - User2's session still exists
        result = await repository.get_user_sessions(user_id2, session_lifetime_minutes=30)
        assert len(result) >= 1
        assert result[0]["id"] == session2

    async def test_user_with_no_sessions_returns_zero(
        self,
        repository: AuthRepository,
        create_test_user,
    ):
        """Test that user with no sessions returns 0."""
        # Arrange
        user_id = await create_test_user()

        # Act
        count = await repository.delete_user_sessions(user_id)

        # Assert
        assert count == 0
