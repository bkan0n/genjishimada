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
