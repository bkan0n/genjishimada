"""Tests for UtilitiesRepository.log_analytics operation."""

import asyncio
import datetime as dt
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
        assert row["namespace"] == namespace

    @pytest.mark.asyncio
    async def test_log_analytics_complex_namespace(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with complex nested namespace."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {
            "level1": {
                "level2": {
                    "level3": "deep_value",
                    "array": [1, 2, 3],
                },
                "mixed": ["string", 123, True, None],
            },
            "top_level": "value",
        }

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert
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
        assert row["namespace"] == namespace
        assert row["namespace"]["level1"]["level2"]["level3"] == "deep_value"

    @pytest.mark.asyncio
    async def test_log_analytics_sequential_inserts(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test multiple sequential inserts with same command/user but different timestamps."""
        # Arrange
        command_name = fake.word()
        entries = []

        # Act - Insert 3 entries with microsecond differences
        for i in range(3):
            created_at = dt.datetime.now(dt.timezone.utc)
            namespace = {"iteration": i}
            await repository.log_analytics(command_name, unique_user_id, created_at, namespace)
            entries.append((created_at, namespace))
            # Small delay to ensure different timestamps
            await asyncio.sleep(0.001)

        # Assert - All 3 should exist
        rows = await asyncpg_conn.fetch(
            """
            SELECT created_at, namespace
            FROM public.analytics
            WHERE command_name = $1 AND user_id = $2
            ORDER BY created_at ASC
            """,
            command_name,
            unique_user_id,
        )

        assert len(rows) == 3
        for i, row in enumerate(rows):
            assert row["namespace"]["iteration"] == i


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestLogAnalyticsEdgeCases:
    """Test edge cases for log_analytics."""

    @pytest.mark.asyncio
    async def test_log_analytics_empty_namespace(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with empty namespace dict."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {}

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert
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
        assert row["namespace"] == {}

    @pytest.mark.asyncio
    async def test_log_analytics_namespace_with_nulls(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with null values in namespace."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {"key1": None, "key2": "value", "key3": None}

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert
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
        assert row["namespace"] == namespace
        assert row["namespace"]["key1"] is None

    @pytest.mark.asyncio
    async def test_log_analytics_special_characters_in_command_name(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with special characters in command name."""
        # Arrange
        command_name = "command/with:special-chars_and.dots"
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {"test": True}

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT command_name
            FROM public.analytics
            WHERE command_name = $1 AND user_id = $2
            """,
            command_name,
            unique_user_id,
        )

        assert row is not None
        assert row["command_name"] == command_name

    @pytest.mark.asyncio
    async def test_log_analytics_unicode_in_namespace(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with unicode characters in namespace."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        namespace = {
            "emoji": "🎮🏆",
            "japanese": "こんにちは",
            "chinese": "你好",
            "arabic": "مرحبا",
            "mixed": "Hello 世界 🌍",
        }

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert
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
        assert row["namespace"] == namespace
        assert row["namespace"]["emoji"] == "🎮🏆"

    @pytest.mark.asyncio
    async def test_log_analytics_large_namespace(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test logging analytics with large namespace payload."""
        # Arrange
        command_name = fake.word()
        created_at = dt.datetime.now(dt.timezone.utc)
        # Create a large namespace with many keys
        namespace = {f"key_{i}": fake.sentence(nb_words=20) for i in range(100)}

        # Act
        await repository.log_analytics(command_name, unique_user_id, created_at, namespace)

        # Assert
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
        assert len(row["namespace"]) == 100


# ==============================================================================
# CONCURRENCY TESTS
# ==============================================================================


class TestLogAnalyticsConcurrency:
    """Test concurrent operations for log_analytics."""

    @pytest.mark.asyncio
    async def test_log_analytics_parallel_inserts(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        global_user_id_tracker: set[int],
    ) -> None:
        """Test parallel inserts don't cause issues."""
        # Arrange
        command_name = fake.word()
        user_ids = []
        for _ in range(5):
            user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            if user_id not in global_user_id_tracker:
                global_user_id_tracker.add(user_id)
                user_ids.append(user_id)

        # Act - Insert concurrently
        tasks = []
        for user_id in user_ids:
            created_at = dt.datetime.now(dt.timezone.utc)
            namespace = {"user": user_id}
            tasks.append(repository.log_analytics(command_name, user_id, created_at, namespace))

        await asyncio.gather(*tasks)

        # Assert - All should be inserted
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM public.analytics
            WHERE command_name = $1
            """,
            command_name,
        )

        assert count == len(user_ids)


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
        assert row["namespace"]["test"] == "commit"

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
