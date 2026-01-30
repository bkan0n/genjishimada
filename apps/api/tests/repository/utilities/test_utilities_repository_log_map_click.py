"""Tests for UtilitiesRepository.log_map_click operation."""

import asyncio
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


class TestLogMapClickHappyPath:
    """Test happy path scenarios for log_map_click."""

    @pytest.mark.asyncio
    async def test_log_map_click_authenticated_user(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test logging map click with authenticated user."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web"

        # Act
        await repository.log_map_click(unique_map_code, user_id, source, unique_ip_hash)

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT map_id, user_id, source, ip_hash
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        assert row is not None
        assert row["map_id"] == map_id
        assert row["user_id"] == user_id
        assert row["source"] == source
        assert row["ip_hash"] == unique_ip_hash

    @pytest.mark.asyncio
    async def test_log_map_click_anonymous_user(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test logging map click with anonymous user (user_id=None)."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        source = "web"

        # Act
        await repository.log_map_click(unique_map_code, None, source, unique_ip_hash)

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT map_id, user_id, source, ip_hash
            FROM maps.clicks
            WHERE map_id = $1 AND ip_hash = $2
            """,
            map_id,
            unique_ip_hash,
        )

        assert row is not None
        assert row["map_id"] == map_id
        assert row["user_id"] is None
        assert row["source"] == source
        assert row["ip_hash"] == unique_ip_hash

    @pytest.mark.asyncio
    async def test_log_map_click_different_sources(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        global_ip_hash_tracker: set[str],
    ) -> None:
        """Test logging clicks from different sources."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        import hashlib

        ip_hash_web = hashlib.sha256(uuid4().bytes).hexdigest()
        ip_hash_bot = hashlib.sha256(uuid4().bytes).hexdigest()
        global_ip_hash_tracker.add(ip_hash_web)
        global_ip_hash_tracker.add(ip_hash_bot)

        # Act - Log click from web
        await repository.log_map_click(unique_map_code, user_id, "web", ip_hash_web)

        # Act - Log click from bot
        await repository.log_map_click(unique_map_code, user_id, "bot", ip_hash_bot)

        # Assert - Both should exist
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        assert count == 2


# ==============================================================================
# ON CONFLICT / DEDUPLICATION TESTS
# ==============================================================================


class TestLogMapClickDeduplication:
    """Test ON CONFLICT deduplication behavior."""

    @pytest.mark.asyncio
    async def test_log_map_click_duplicate_same_day_ignored(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test that duplicate click on same day is silently ignored via ON CONFLICT."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web"

        # Act - Log same click twice
        await repository.log_map_click(unique_map_code, user_id, source, unique_ip_hash)
        await repository.log_map_click(unique_map_code, user_id, source, unique_ip_hash)

        # Assert - Only one record should exist
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM maps.clicks
            WHERE map_id = $1 AND ip_hash = $2
            """,
            map_id,
            unique_ip_hash,
        )

        assert count == 1

    @pytest.mark.asyncio
    async def test_log_map_click_different_ip_not_deduplicated(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        unique_map_code: str,
        create_test_user,
        global_ip_hash_tracker: set[str],
    ) -> None:
        """Test that clicks from different IPs are not deduplicated."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web"
        import hashlib

        ip_hash_1 = hashlib.sha256(uuid4().bytes).hexdigest()
        ip_hash_2 = hashlib.sha256(uuid4().bytes).hexdigest()
        global_ip_hash_tracker.add(ip_hash_1)
        global_ip_hash_tracker.add(ip_hash_2)

        # Act
        await repository.log_map_click(unique_map_code, user_id, source, ip_hash_1)
        await repository.log_map_click(unique_map_code, user_id, source, ip_hash_2)

        # Assert - Both should exist
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        assert count == 2


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestLogMapClickEdgeCases:
    """Test edge cases for log_map_click."""

    @pytest.mark.asyncio
    async def test_log_map_click_nonexistent_map_code(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_user,
        unique_ip_hash: str,
    ) -> None:
        """Test logging click for non-existent map code."""
        # Arrange
        import asyncpg.exceptions

        user_id = await create_test_user()
        nonexistent_code = f"NOEXIST{uuid4().hex[:5].upper()}"
        source = "web"

        # Act & Assert
        # The CTE will return NULL for map_id, which causes INSERT to fail
        # with NOT NULL constraint violation
        with pytest.raises(asyncpg.exceptions.NotNullViolationError) as exc_info:
            await repository.log_map_click(nonexistent_code, user_id, source, unique_ip_hash)

        # Verify the error is about map_id being NULL
        assert "map_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_log_map_click_case_insensitive_code(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        global_code_tracker: set[str],
        create_test_user,
        unique_ip_hash: str,
    ) -> None:
        """Test logging click with different case map code."""
        # Arrange
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)
        map_id = await create_test_map(code)
        user_id = await create_test_user()
        source = "web"

        # Act - Use lowercase version
        await repository.log_map_click(code.lower(), user_id, source, unique_ip_hash)

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT map_id
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        # Map codes are case-insensitive in the database
        assert row is not None

    @pytest.mark.asyncio
    async def test_log_map_click_special_characters_in_source(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        unique_map_code: str,
        create_test_user,
        unique_ip_hash: str,
    ) -> None:
        """Test logging click with special characters in source."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web/embed:special-chars"

        # Act
        await repository.log_map_click(unique_map_code, user_id, source, unique_ip_hash)

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT source
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        assert row is not None
        assert row["source"] == source


# ==============================================================================
# CONCURRENCY TESTS
# ==============================================================================


class TestLogMapClickConcurrency:
    """Test concurrent operations for log_map_click."""

    @pytest.mark.asyncio
    async def test_log_map_click_parallel_different_users(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        unique_map_code: str,
        global_user_id_tracker: set[int],
        global_ip_hash_tracker: set[str],
    ) -> None:
        """Test parallel clicks from different users to same map."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        source = "web"
        user_ids = []
        ip_hashes = []

        import hashlib

        for _ in range(5):
            user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            if user_id not in global_user_id_tracker:
                global_user_id_tracker.add(user_id)
                user_ids.append(user_id)

            ip_hash = hashlib.sha256(uuid4().bytes).hexdigest()
            global_ip_hash_tracker.add(ip_hash)
            ip_hashes.append(ip_hash)

        # Act - Log clicks concurrently
        tasks = []
        for user_id, ip_hash in zip(user_ids, ip_hashes):
            tasks.append(repository.log_map_click(unique_map_code, user_id, source, ip_hash))

        await asyncio.gather(*tasks)

        # Assert - All should be inserted
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM maps.clicks
            WHERE map_id = $1
            """,
            map_id,
        )

        assert count == len(user_ids)


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestLogMapClickTransactions:
    """Test transaction behavior for log_map_click."""

    @pytest.mark.asyncio
    async def test_log_map_click_transaction_commit(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        unique_map_code: str,
        create_test_user,
        unique_ip_hash: str,
    ) -> None:
        """Test click persists when transaction commits."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web"

        # Act
        async with asyncpg_conn.transaction():
            await repository.log_map_click(
                unique_map_code, user_id, source, unique_ip_hash, conn=asyncpg_conn
            )

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT map_id
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        assert row is not None

    @pytest.mark.asyncio
    async def test_log_map_click_transaction_rollback(
        self,
        asyncpg_conn,
        create_test_map,
        unique_map_code: str,
        create_test_user,
        unique_ip_hash: str,
    ) -> None:
        """Test click doesn't persist when transaction rolls back."""
        # Arrange
        repository = UtilitiesRepository(asyncpg_conn)
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web"

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.log_map_click(
                    unique_map_code, user_id, source, unique_ip_hash, conn=asyncpg_conn
                )
                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert
        row = await asyncpg_conn.fetchrow(
            """
            SELECT map_id
            FROM maps.clicks
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
        )

        assert row is None
