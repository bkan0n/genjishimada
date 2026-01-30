"""Tests for UtilitiesRepository.log_analytics operation."""

import asyncio
import datetime as dt
import json
from uuid import uuid4

import pytest
from faker import Faker

from repository.utilities_repository import UtilitiesRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_utilities,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide utilities repository instance."""
    return UtilitiesRepository(asyncpg_conn)


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestLogAnalyticsHappyPath:
    """Test happy path scenarios for log_analytics."""

    @pytest.mark.asyncio
    async def test_log_analytics_basic_insert(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with basic data succeeds."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {"key": "value", "count": 42}

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert - Verify data was inserted
        row = await asyncpg_conn.fetchrow(
            """
            SELECT command_name, user_id, created_at, namespace
            FROM public.analytics
            WHERE command_name = $1 AND user_id = $2
            """,
            command_name,
            unique_user_id,
        )

        assert row is not None
        assert row["command_name"] == command_name
        assert row["user_id"] == unique_user_id
        assert row["namespace"] == json.dumps(namespace)


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================

# ==============================================================================
# CONCURRENCY TESTS
# ==============================================================================



# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestLogAnalyticsTransactions:
    """Test transaction behavior for log_analytics."""

    @pytest.mark.asyncio
    async def test_log_analytics_transaction_commit(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test analytics persists when transaction commits."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {"test": "commit"}

        # Act
        async with asyncpg_conn.transaction():
            await repository.log_analytics(
                command_name, unique_user_id, created_at, namespace, conn=asyncpg_conn
            )

        # Assert - Data should persist
        row = await asyncpg_conn.fetchrow(
            """
            SELECT namespace
            FROM public.analytics
            WHERE command_name = $1 AND user_id = $2
            """,
            command_name,
            unique_user_id,
        )

        assert row is not None

    @pytest.mark.asyncio
    async def test_log_analytics_transaction_rollback(
        self,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test analytics doesn't persist when transaction rolls back."""
        # Arrange
        repository = UtilitiesRepository(asyncpg_conn)
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {"test": "rollback"}

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.log_analytics(
                    command_name, unique_user_id, created_at, namespace, conn=asyncpg_conn
                )
                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - Data should NOT persist
        row = await asyncpg_conn.fetchrow(
            """
            SELECT namespace
            FROM public.analytics
            WHERE command_name = $1 AND user_id = $2
            """,
            command_name,
            unique_user_id,
        )

        assert row is None
