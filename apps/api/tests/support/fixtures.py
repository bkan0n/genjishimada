"""Explicit database and HTTP fixtures; importing them never starts PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import psycopg
import pytest
from litestar import Litestar
from pytest_databases.docker.postgres import PostgresService

from app import _async_pg_init
from tests.support.database import DatabaseBaseline, migrate


@pytest.fixture(scope="session")
def xdist_postgres_isolation_level() -> str:
    return "database"


@pytest.fixture(scope="session")
def database_url(postgres_service: PostgresService) -> str:
    service = postgres_service
    return f"postgresql://{service.user}:{service.password}@{service.host}:{service.port}/{service.database}"


@pytest.fixture(scope="session")
def database_baseline(postgres_connection: psycopg.Connection, postgres_service: PostgresService) -> DatabaseBaseline:
    actual = postgres_connection.execute("SELECT current_database()").fetchone()[0]
    if actual != postgres_service.database or not actual.startswith("pytest_databases"):
        raise RuntimeError("Database reset requires the fixture-owned pytest database")
    postgres_connection.commit()
    migrate(postgres_connection)
    return DatabaseBaseline.capture(postgres_connection)


@pytest.fixture
def isolated_database(database_baseline: DatabaseBaseline, postgres_connection: psycopg.Connection) -> None:
    database_baseline.restore(postgres_connection)


@pytest.fixture
async def asyncpg_conn(isolated_database: None, database_url: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(database_url, command_timeout=30, server_settings={"lock_timeout": "5s"})
    try:
        await _async_pg_init(conn)
        yield conn
    finally:
        await conn.close(timeout=5)


@pytest.fixture
async def asyncpg_pool(isolated_database: None, database_url: str) -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=3,
        init=_async_pg_init,
        command_timeout=30,
        server_settings={"lock_timeout": "5s"},
    )
    try:
        yield pool
    finally:
        # A leaked checkout must identify the failing test instead of hanging
        # every later test assigned to this worker. close() terminates on cancel.
        await asyncio.wait_for(pool.close(), timeout=10)


@pytest.fixture
def app(isolated_database: None, database_url: str) -> Litestar:
    from tests.support.application import create_test_app

    return create_test_app(database_url)


@pytest.fixture
async def test_client(app: Litestar):
    from tests.support.application import TestClient

    async with TestClient(app=app) as client:
        client.headers.update({"x-pytest-enabled": "1", "X-API-KEY": "testing"})
        yield client


@pytest.fixture
async def unauthenticated_client(app: Litestar):
    from tests.support.application import TestClient

    async with TestClient(app=app) as client:
        client.headers.update({"x-pytest-enabled": "1"})
        yield client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-KEY": "testing", "x-pytest-enabled": "1"}


@pytest.fixture
def no_auth_headers() -> dict[str, str]:
    return {"x-pytest-enabled": "1"}
