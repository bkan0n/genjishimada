"""Tests for UtilitiesRepository.fetch_map_clicks_debug operation."""

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


class TestFetchMapClicksDebugHappyPath:
    """Test happy path scenarios for fetch_map_clicks_debug."""

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_default_limit(
        self,
        repository: UtilitiesRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        global_ip_hash_tracker: set[str],
    ) -> None:
        """Test fetching clicks with default limit (100)."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        import hashlib

        # Create 5 clicks
        for i in range(5):
            ip_hash = hashlib.sha256(uuid4().bytes).hexdigest()
            global_ip_hash_tracker.add(ip_hash)
            await repository.log_map_click(unique_map_code, user_id, "web", ip_hash)

        # Act
        results = await repository.fetch_map_clicks_debug()

        # Assert - Should return at least our 5 clicks
        assert isinstance(results, list)
        assert len(results) >= 5

        # Verify results have expected fields
        for result in results[:5]:
            assert "id" in result
            assert "map_id" in result
            assert "user_id" in result
            assert "source" in result
            assert "ip_hash" in result
            assert "inserted_at" in result

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_custom_limit(
        self,
        repository: UtilitiesRepository,
        create_test_map,
        create_test_user,
        global_code_tracker: set[str],
        global_ip_hash_tracker: set[str],
    ) -> None:
        """Test fetching clicks with custom limit."""
        # Arrange - Create 10 clicks
        import hashlib

        for i in range(10):
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)
            map_id = await create_test_map(code)
            user_id = await create_test_user()

            ip_hash = hashlib.sha256(uuid4().bytes).hexdigest()
            global_ip_hash_tracker.add(ip_hash)

            await repository.log_map_click(code, user_id, "web", ip_hash)

        # Act - Fetch only 5
        results = await repository.fetch_map_clicks_debug(limit=5)

        # Assert
        assert isinstance(results, list)
        assert len(results) >= 5  # At least 5 (might be more from other tests)

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_ordered_by_time(
        self,
        repository: UtilitiesRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        global_ip_hash_tracker: set[str],
    ) -> None:
        """Test fetching clicks returns most recent first (DESC order)."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        import hashlib

        # Create 3 clicks with small delays
        ip_hashes = []
        for i in range(3):
            ip_hash = hashlib.sha256(uuid4().bytes).hexdigest()
            global_ip_hash_tracker.add(ip_hash)
            ip_hashes.append(ip_hash)

            await repository.log_map_click(unique_map_code, user_id, "web", ip_hash)
            # Small delay to ensure different timestamps
            await asyncio.sleep(0.01)

        # Act
        results = await repository.fetch_map_clicks_debug(limit=10)

        # Assert - Results should be in DESC order (most recent first)
        # Find our clicks in the results
        our_clicks = [r for r in results if r["ip_hash"] in ip_hashes]
        assert len(our_clicks) == 3

        # Verify they're in descending timestamp order
        for i in range(len(our_clicks) - 1):
            assert our_clicks[i]["inserted_at"] >= our_clicks[i + 1]["inserted_at"]


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestFetchMapClicksDebugEdgeCases:
    """Test edge cases for fetch_map_clicks_debug."""

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_limit_zero(
        self,
        repository: UtilitiesRepository,
    ) -> None:
        """Test fetching with limit=0 returns empty list."""
        # Act
        results = await repository.fetch_map_clicks_debug(limit=0)

        # Assert
        assert isinstance(results, list)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_limit_one(
        self,
        repository: UtilitiesRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test fetching with limit=1 returns only one result."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        await repository.log_map_click(unique_map_code, user_id, "web", unique_ip_hash)

        # Act
        results = await repository.fetch_map_clicks_debug(limit=1)

        # Assert
        assert isinstance(results, list)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_large_limit(
        self,
        repository: UtilitiesRepository,
    ) -> None:
        """Test fetching with very large limit doesn't cause issues."""
        # Act
        results = await repository.fetch_map_clicks_debug(limit=10000)

        # Assert
        assert isinstance(results, list)
        # Should return all clicks up to the limit

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_all_fields_returned(
        self,
        repository: UtilitiesRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test that all expected fields are returned in dict format."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        await repository.log_map_click(unique_map_code, user_id, "web", unique_ip_hash)

        # Act
        results = await repository.fetch_map_clicks_debug(limit=10)

        # Assert
        our_click = next((r for r in results if r["ip_hash"] == unique_ip_hash), None)
        assert our_click is not None

        # Verify all fields are present
        expected_fields = [
            "id",
            "map_id",
            "user_id",
            "source",
            "user_agent",
            "ip_hash",
            "inserted_at",
            "day_bucket",
        ]
        for field in expected_fields:
            assert field in our_click

        # Verify data types
        assert isinstance(our_click["id"], int)
        assert isinstance(our_click["map_id"], int)
        assert isinstance(our_click["user_id"], int)
        assert isinstance(our_click["source"], str)
        assert isinstance(our_click["ip_hash"], str)

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_dict_conversion(
        self,
        repository: UtilitiesRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test that results are properly converted to dicts."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        source = "web"
        await repository.log_map_click(unique_map_code, user_id, source, unique_ip_hash)

        # Act
        results = await repository.fetch_map_clicks_debug(limit=10)

        # Assert
        our_click = next((r for r in results if r["ip_hash"] == unique_ip_hash), None)
        assert our_click is not None

        # Verify it's a dict and values match
        assert isinstance(our_click, dict)
        assert our_click["map_id"] == map_id
        assert our_click["user_id"] == user_id
        assert our_click["source"] == source
        assert our_click["ip_hash"] == unique_ip_hash


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestFetchMapClicksDebugTransactions:
    """Test transaction behavior for fetch_map_clicks_debug."""

    @pytest.mark.asyncio
    async def test_fetch_map_clicks_debug_within_transaction(
        self,
        repository: UtilitiesRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        unique_ip_hash: str,
    ) -> None:
        """Test fetching clicks within a transaction."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Act - Fetch within transaction
        async with asyncpg_conn.transaction():
            await repository.log_map_click(
                unique_map_code, user_id, "web", unique_ip_hash, conn=asyncpg_conn
            )
            results = await repository.fetch_map_clicks_debug(conn=asyncpg_conn)

        # Assert
        assert isinstance(results, list)
        our_click = next((r for r in results if r["ip_hash"] == unique_ip_hash), None)
        assert our_click is not None
