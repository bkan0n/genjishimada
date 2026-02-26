"""Test that conftest.py fixtures work correctly."""

import asyncpg
from litestar.testing import AsyncTestClient


async def test_database_connection(asyncpg_conn: asyncpg.Connection) -> None:
    """Test that database connection fixture works."""
    result = await asyncpg_conn.fetchval("SELECT 1")
    assert result == 1


async def test_client_headers(test_client: AsyncTestClient) -> None:
    """Test that test client has required headers."""
    assert test_client.headers["x-pytest-enabled"] == "1"
    assert test_client.headers["X-API-KEY"] == "testing"


async def test_database_has_migrations(asyncpg_conn: asyncpg.Connection) -> None:
    """Test that database migrations were applied."""
    # Check that a table from our first migration exists
    result = await asyncpg_conn.fetchval(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'users')"
    )
    assert result is True


