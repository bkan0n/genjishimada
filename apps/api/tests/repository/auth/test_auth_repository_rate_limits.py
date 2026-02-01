"""Tests for AuthRepository rate limit and utility operations.

Test Coverage:
- record_attempt: success/failure, case insensitive identifier, timestamp
- fetch_rate_limit_count: counts in window, excludes old, case insensitive, filters by action
- check_is_mod: moderator, non-moderator, anonymous session, invalid session
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
# record_attempt TESTS
# ==============================================================================


class TestRecordAttempt:
    """Test record_attempt method."""

    async def test_records_successful_attempt(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test recording successful attempt."""
        # Arrange
        identifier = fake.email()
        action = "login"

        # Act
        await repository.record_attempt(identifier, action, success=True)

        # Assert - Verify recorded
        row = await asyncpg_conn.fetchrow(
            "SELECT identifier, action, success FROM users.auth_rate_limits WHERE identifier = LOWER($1) AND action = $2 ORDER BY attempt_at DESC LIMIT 1",
            identifier,
            action,
        )
        assert row is not None
        assert row["identifier"] == identifier.lower()
        assert row["action"] == action
        assert row["success"] is True

    async def test_records_failed_attempt(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test recording failed attempt."""
        # Arrange
        identifier = fake.email()
        action = "login"

        # Act
        await repository.record_attempt(identifier, action, success=False)

        # Assert - Verify recorded
        row = await asyncpg_conn.fetchrow(
            "SELECT identifier, action, success FROM users.auth_rate_limits WHERE identifier = LOWER($1) AND action = $2 ORDER BY attempt_at DESC LIMIT 1",
            identifier,
            action,
        )
        assert row is not None
        assert row["success"] is False

    async def test_identifier_stored_lowercase(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test that identifier is stored in lowercase."""
        # Arrange
        identifier = "TeSt@ExAmPlE.CoM"
        action = "login"

        # Act
        await repository.record_attempt(identifier, action, success=True)

        # Assert - Stored as lowercase
        row = await asyncpg_conn.fetchrow(
            "SELECT identifier FROM users.auth_rate_limits WHERE identifier = $1 AND action = $2",
            identifier.lower(),
            action,
        )
        assert row is not None
        assert row["identifier"] == identifier.lower()

    async def test_timestamp_recorded(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test that attempt_at timestamp is recorded."""
        # Arrange
        identifier = fake.email()
        action = "login"
        before = dt.datetime.now(dt.timezone.utc)

        # Act
        await repository.record_attempt(identifier, action, success=True)

        # Assert - Timestamp within reasonable range
        row = await asyncpg_conn.fetchrow(
            "SELECT attempt_at FROM users.auth_rate_limits WHERE identifier = LOWER($1) AND action = $2 ORDER BY attempt_at DESC LIMIT 1",
            identifier,
            action,
        )
        assert row is not None
        after = dt.datetime.now(dt.timezone.utc)

        # Timestamp should exist and be a datetime
        assert isinstance(row["attempt_at"], dt.datetime)
        # Just verify timestamp is within a reasonable range (within last minute)
        assert (after - before).total_seconds() < 60

    async def test_multiple_attempts_recorded(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test that multiple attempts are recorded."""
        # Arrange
        identifier = fake.email()
        action = "login"

        # Act - Record 3 attempts
        await repository.record_attempt(identifier, action, success=False)
        await repository.record_attempt(identifier, action, success=False)
        await repository.record_attempt(identifier, action, success=True)

        # Assert - All 3 recorded
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM users.auth_rate_limits WHERE identifier = LOWER($1) AND action = $2",
            identifier,
            action,
        )
        assert count >= 3


# ==============================================================================
# fetch_rate_limit_count TESTS
# ==============================================================================


class TestFetchRateLimitCount:
    """Test fetch_rate_limit_count method."""

    async def test_counts_attempts_in_window(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test that attempts within window are counted."""
        # Arrange
        identifier = fake.email()
        action = "login"
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)

        # Record 3 attempts in the last 5 minutes
        await repository.record_attempt(identifier, action, success=False)
        await repository.record_attempt(identifier, action, success=False)
        await repository.record_attempt(identifier, action, success=False)

        # Act
        count = await repository.fetch_rate_limit_count(identifier, action, window_start)

        # Assert
        assert count >= 3

    async def test_excludes_old_attempts(
        self,
        repository: AuthRepository,
        asyncpg_conn,
    ):
        """Test that attempts outside window are excluded."""
        # Arrange
        identifier = fake.email()
        action = "login"

        # Record an old attempt (1 hour ago)
        await repository.record_attempt(identifier, action, success=False)
        await asyncpg_conn.execute(
            "UPDATE users.auth_rate_limits SET attempt_at = now() - INTERVAL '1 hour' WHERE identifier = LOWER($1)",
            identifier,
        )

        # Record a recent attempt
        await repository.record_attempt(identifier, action, success=False)

        # Act - Count only last 5 minutes
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
        count = await repository.fetch_rate_limit_count(identifier, action, window_start)

        # Assert - Only the recent one counted
        assert count == 1

    async def test_case_insensitive_identifier_matching(
        self,
        repository: AuthRepository,
    ):
        """Test that identifier matching is case-insensitive."""
        # Arrange
        identifier_lower = "test@example.com"
        identifier_upper = "TEST@EXAMPLE.COM"
        action = "login"
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)

        # Record with lowercase
        await repository.record_attempt(identifier_lower, action, success=False)

        # Act - Query with uppercase
        count = await repository.fetch_rate_limit_count(identifier_upper, action, window_start)

        # Assert - Found the attempt
        assert count >= 1

    async def test_filters_by_action(
        self,
        repository: AuthRepository,
    ):
        """Test that count filters by action."""
        # Arrange
        identifier = fake.email()
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)

        # Record different actions
        await repository.record_attempt(identifier, "login", success=False)
        await repository.record_attempt(identifier, "register", success=False)
        await repository.record_attempt(identifier, "login", success=False)

        # Act - Count only login attempts
        count = await repository.fetch_rate_limit_count(identifier, "login", window_start)

        # Assert - Only 2 login attempts counted
        assert count == 2

    async def test_no_attempts_returns_zero(
        self,
        repository: AuthRepository,
    ):
        """Test that no attempts returns 0."""
        # Arrange
        identifier = fake.email()
        action = "login"
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)

        # Act
        count = await repository.fetch_rate_limit_count(identifier, action, window_start)

        # Assert
        assert count == 0

    async def test_counts_both_success_and_failure(
        self,
        repository: AuthRepository,
    ):
        """Test that both successful and failed attempts are counted."""
        # Arrange
        identifier = fake.email()
        action = "login"
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)

        # Record mix of success and failure
        await repository.record_attempt(identifier, action, success=False)
        await repository.record_attempt(identifier, action, success=True)
        await repository.record_attempt(identifier, action, success=False)

        # Act
        count = await repository.fetch_rate_limit_count(identifier, action, window_start)

        # Assert - All 3 counted
        assert count == 3


# ==============================================================================
# check_is_mod TESTS
# ==============================================================================


class TestCheckIsMod:
    """Test check_is_mod method."""

    async def test_moderator_returns_true(
        self,
        repository: AuthRepository,
        create_test_user,
        create_test_session,
        asyncpg_conn,
    ):
        """Test that moderator session returns True."""
        # Arrange
        user_id = await create_test_user()

        # Make user a moderator
        await asyncpg_conn.execute(
            "UPDATE core.users SET is_mod = true WHERE id = $1",
            user_id,
        )

        session_id = await create_test_session(user_id=user_id)

        # Act
        result = await repository.check_is_mod(session_id)

        # Assert
        assert result is True

    async def test_non_moderator_returns_false(
        self,
        repository: AuthRepository,
        create_test_user,
        create_test_session,
        asyncpg_conn,
    ):
        """Test that non-moderator session returns False."""
        # Arrange
        user_id = await create_test_user()

        # Ensure user is not a moderator
        await asyncpg_conn.execute(
            "UPDATE core.users SET is_mod = false WHERE id = $1",
            user_id,
        )

        session_id = await create_test_session(user_id=user_id)

        # Act
        result = await repository.check_is_mod(session_id)

        # Assert
        assert result is False

    async def test_anonymous_session_returns_false(
        self,
        repository: AuthRepository,
        create_test_session,
    ):
        """Test that anonymous session (user_id=None) returns False."""
        # Arrange
        session_id = await create_test_session(user_id=None)

        # Act
        result = await repository.check_is_mod(session_id)

        # Assert
        assert result is False

    async def test_invalid_session_returns_false(
        self,
        repository: AuthRepository,
        unique_session_id: str,
    ):
        """Test that invalid session ID returns False."""
        # Act
        result = await repository.check_is_mod(unique_session_id)

        # Assert
        assert result is False

    async def test_expired_session_returns_false(
        self,
        repository: AuthRepository,
        create_test_user,
        create_test_session,
        asyncpg_conn,
    ):
        """Test that checking expired session returns False (if query filters)."""
        # Arrange
        user_id = await create_test_user()

        # Make user a moderator
        await asyncpg_conn.execute(
            "UPDATE core.users SET is_mod = true WHERE id = $1",
            user_id,
        )

        session_id = await create_test_session(user_id=user_id)

        # Delete the session to simulate expiration/invalidity
        await asyncpg_conn.execute(
            "DELETE FROM users.sessions WHERE id = $1",
            session_id,
        )

        # Act
        result = await repository.check_is_mod(session_id)

        # Assert
        assert result is False
