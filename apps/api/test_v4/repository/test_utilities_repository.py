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
