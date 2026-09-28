"""Test that conftest.py fixtures work correctly."""

import threading
from unittest.mock import patch

import asyncpg
import psycopg
import pytest
from litestar.events.emitter import SimpleEventEmitter
from litestar.testing import AsyncTestClient

from app import app as production_app
from app import skill_nightly_rebuild_poller, tournament_outbox_poller
from tests.support.application import DeterministicEventEmitter, create_test_app
from tests.support.database import DatabaseBaseline

pytestmark = [pytest.mark.database, pytest.mark.integration]


async def test_database_connection(asyncpg_conn: asyncpg.Connection) -> None:
    """Test that database connection fixture works."""
    result = await asyncpg_conn.fetchval("SELECT 1")
    assert result == 1
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM core.users") == 0
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM core.maps") == 0


async def test_client_headers(test_client: AsyncTestClient, database_url: str) -> None:
    """Test that test client has required headers."""
    assert test_client.headers["x-pytest-enabled"] == "1"
    assert test_client.headers["X-API-KEY"] == "testing"
    assert isinstance(production_app.event_emitter, SimpleEventEmitter)
    assert isinstance(test_client.app.event_emitter, DeterministicEventEmitter)
    for poller in (tournament_outbox_poller, skill_nightly_rebuild_poller):
        assert poller in production_app._lifespan_managers
        assert poller not in test_client.app._lifespan_managers

    # Constructing another app must not accumulate process-wide telemetry or
    # logging workers. A full serial suite creates hundreds of app instances.
    threads_before = {thread.ident for thread in threading.enumerate()}
    with patch("app.sentry_sdk.init") as initialize_sentry:
        for _ in range(3):
            extra_app = create_test_app(database_url)
            assert extra_app.logger is not None
        initialize_sentry.assert_not_called()
    assert {thread.ident for thread in threading.enumerate()} <= threads_before


async def test_database_has_migrations(
    asyncpg_conn: asyncpg.Connection,
    database_baseline: DatabaseBaseline,
    postgres_connection: psycopg.Connection,
) -> None:
    """Test that database migrations were applied."""
    # Check that a table from our first migration exists
    result = await asyncpg_conn.fetchval(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'core' AND table_name = 'users')"
    )
    assert result is True

    # Reference data is mutable: isolation must restore its values as well as
    # removing test-created rows, regardless of which test runs next.
    before = await asyncpg_conn.fetchrow(
        "SELECT (SELECT rotation_period_days FROM store.config) AS rotation_days, "
        "(SELECT gamma FROM skill.weight_config) AS gamma, "
        "(SELECT blacklist_weeks FROM tournaments.config) AS blacklist_weeks"
    )
    assert before is not None
    assert before["rotation_days"] == 7
    assert before["gamma"] == 0.68
    await asyncpg_conn.execute(
        "INSERT INTO core.users (id, nickname, global_name) "
        "VALUES (123456789012345678, 'reset-probe', 'reset-probe'); "
        "INSERT INTO maps.names (name) VALUES ('Fixture Reset Probe'); "
        "UPDATE store.config SET rotation_period_days = 31; "
        "UPDATE skill.weight_config SET gamma = 0.9; "
        "UPDATE tournaments.config SET blacklist_weeks = 99"
    )

    database_baseline.restore(postgres_connection)

    after = await asyncpg_conn.fetchrow(
        "SELECT (SELECT rotation_period_days FROM store.config) AS rotation_days, "
        "(SELECT gamma FROM skill.weight_config) AS gamma, "
        "(SELECT blacklist_weeks FROM tournaments.config) AS blacklist_weeks"
    )
    assert after == before
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM core.users") == 0
    assert not await asyncpg_conn.fetchval("SELECT EXISTS (SELECT FROM maps.names WHERE name = 'Fixture Reset Probe')")
    assert await asyncpg_conn.fetchval("SELECT EXISTS (SELECT FROM maps.names WHERE name = 'Hanamura')")
    assert await asyncpg_conn.fetchval("SELECT EXISTS (SELECT FROM public.api_tokens WHERE api_key = 'testing')")
