"""Tests for UtilitiesRepository."""

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.utilities_repository import UtilitiesRepository


@pytest.fixture
async def db_pool(postgres_service: PostgresService):
    """Create asyncpg pool for tests."""
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def utilities_repo(db_pool: asyncpg.Pool) -> UtilitiesRepository:
    """Create repository instance."""
    return UtilitiesRepository(db_pool)


class TestUtilitiesQueries:
    """Test repository methods."""

    async def test_log_analytics_inserts_record(self, utilities_repo: UtilitiesRepository):
        """Test that analytics logging works."""
        import datetime as dt

        await utilities_repo.log_analytics(
            command_name="test_command",
            user_id=123,
            created_at=dt.datetime.now(dt.timezone.utc),
            namespace={"test": "data"},
        )
        # No assertion needed - just verify no exception

    async def test_log_map_click_inserts_record(self, utilities_repo: UtilitiesRepository, db_pool: asyncpg.Pool):
        """Test map click logging."""
        # Create test map
        async with db_pool.acquire() as conn:
            map_id = await conn.fetchval(
                "INSERT INTO core.maps (code, map_name, category, checkpoints, difficulty, raw_difficulty) "
                "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                "TEST12", "Test Map", "Parkour", 10, "Easy", 1.0
            )

        await utilities_repo.log_map_click(
            code="TEST12",
            user_id=None,
            source="web",
            ip_hash="test_hash",
        )

        # Verify insertion
        async with db_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM maps.clicks WHERE map_id = $1", map_id)
        assert count == 1
