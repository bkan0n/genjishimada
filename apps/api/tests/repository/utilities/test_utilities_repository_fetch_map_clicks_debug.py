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
