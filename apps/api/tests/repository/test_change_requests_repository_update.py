"""Tests for ChangeRequestsRepository update operations.

Test Coverage:
- Happy path: mark_resolved sets resolved flag
- Happy path: mark_alerted sets alerted flag
- Idempotency: multiple calls work safely
- Edge case: update non-existent record is idempotent
- Transaction behavior: rollback reverts changes
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.change_requests_repository import ChangeRequestsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_change_requests,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide change_requests repository instance."""
    return ChangeRequestsRepository(asyncpg_conn)


# ==============================================================================
# MARK_RESOLVED TESTS
# ==============================================================================


class TestMarkResolvedHappyPath:
    """Test happy path scenarios for mark_resolved."""

    @pytest.mark.asyncio
    async def test_mark_resolved_sets_flag(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test marking change request as resolved sets the flag."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
        )

        # Verify initial state
        row = await asyncpg_conn.fetchrow(
            "SELECT resolved FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["resolved"] is False

        # Act
        await repository.mark_resolved(thread_id)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT resolved FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["resolved"] is True

    @pytest.mark.asyncio
    async def test_mark_resolved_is_idempotent(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test marking as resolved multiple times is idempotent."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
        )

        # Act - mark resolved multiple times
        await repository.mark_resolved(thread_id)
        await repository.mark_resolved(thread_id)
        await repository.mark_resolved(thread_id)

        # Assert - still resolved
        row = await asyncpg_conn.fetchrow(
            "SELECT resolved FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["resolved"] is True

    @pytest.mark.asyncio
    async def test_mark_resolved_nonexistent_thread_is_idempotent(
        self,
        repository: ChangeRequestsRepository,
        unique_thread_id: int,
    ):
        """Test marking non-existent thread_id as resolved completes without error."""
        # Act & Assert - should not raise exception
        await repository.mark_resolved(unique_thread_id)


class TestMarkResolvedTransactionBehavior:
    """Test transaction behavior for mark_resolved."""

    @pytest.mark.asyncio
    async def test_mark_resolved_rollback_reverts_change(
        self,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test that rolled back transaction reverts resolved flag."""
        # Arrange
        repository = ChangeRequestsRepository(asyncpg_conn)
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
        )

        # Act - mark resolved within transaction then rollback
        try:
            async with asyncpg_conn.transaction():
                await repository.mark_resolved(thread_id, conn=asyncpg_conn)

                # Verify it was set
                row = await asyncpg_conn.fetchrow(
                    "SELECT resolved FROM change_requests WHERE thread_id = $1",
                    thread_id,
                )
                assert row["resolved"] is True

                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - verify flag is still False after rollback
        row = await asyncpg_conn.fetchrow(
            "SELECT resolved FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["resolved"] is False


# ==============================================================================
# MARK_ALERTED TESTS
# ==============================================================================


class TestMarkAlertedHappyPath:
    """Test happy path scenarios for mark_alerted."""

    @pytest.mark.asyncio
    async def test_mark_alerted_sets_flag(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test marking change request as alerted sets the flag."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            alerted=False,
        )

        # Verify initial state
        row = await asyncpg_conn.fetchrow(
            "SELECT alerted FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["alerted"] is False

        # Act
        await repository.mark_alerted(thread_id)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT alerted FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["alerted"] is True

    @pytest.mark.asyncio
    async def test_mark_alerted_is_idempotent(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test marking as alerted multiple times is idempotent."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            alerted=False,
        )

        # Act - mark alerted multiple times
        await repository.mark_alerted(thread_id)
        await repository.mark_alerted(thread_id)
        await repository.mark_alerted(thread_id)

        # Assert - still alerted
        row = await asyncpg_conn.fetchrow(
            "SELECT alerted FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["alerted"] is True

    @pytest.mark.asyncio
    async def test_mark_alerted_nonexistent_thread_is_idempotent(
        self,
        repository: ChangeRequestsRepository,
        unique_thread_id: int,
    ):
        """Test marking non-existent thread_id as alerted completes without error."""
        # Act & Assert - should not raise exception
        await repository.mark_alerted(unique_thread_id)


class TestMarkAlertedTransactionBehavior:
    """Test transaction behavior for mark_alerted."""

    @pytest.mark.asyncio
    async def test_mark_alerted_rollback_reverts_change(
        self,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test that rolled back transaction reverts alerted flag."""
        # Arrange
        repository = ChangeRequestsRepository(asyncpg_conn)
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            alerted=False,
        )

        # Act - mark alerted within transaction then rollback
        try:
            async with asyncpg_conn.transaction():
                await repository.mark_alerted(thread_id, conn=asyncpg_conn)

                # Verify it was set
                row = await asyncpg_conn.fetchrow(
                    "SELECT alerted FROM change_requests WHERE thread_id = $1",
                    thread_id,
                )
                assert row["alerted"] is True

                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - verify flag is still False after rollback
        row = await asyncpg_conn.fetchrow(
            "SELECT alerted FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["alerted"] is False


# ==============================================================================
# COMBINED FLAG TESTS
# ==============================================================================


class TestCombinedFlagUpdates:
    """Test scenarios with both resolved and alerted flags."""

    @pytest.mark.asyncio
    async def test_mark_both_flags_independently(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test marking both resolved and alerted flags independently."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
            alerted=False,
        )

        # Act - mark resolved first
        await repository.mark_resolved(thread_id)

        # Assert - resolved is True, alerted is still False
        row = await asyncpg_conn.fetchrow(
            "SELECT resolved, alerted FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["resolved"] is True
        assert row["alerted"] is False

        # Act - mark alerted
        await repository.mark_alerted(thread_id)

        # Assert - both are True
        row = await asyncpg_conn.fetchrow(
            "SELECT resolved, alerted FROM change_requests WHERE thread_id = $1",
            thread_id,
        )
        assert row["resolved"] is True
        assert row["alerted"] is True
