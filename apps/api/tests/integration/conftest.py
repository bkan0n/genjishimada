"""Integration test fixtures.

The test_client fixture from root conftest.py is already configured with
auth headers. This file provides additional fixtures for integration tests.
"""

from collections.abc import AsyncIterator

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient
from pytest_databases.docker.postgres import PostgresService


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Valid X-API-KEY header for authenticated requests.

    Note: The root test_client already includes these headers by default.
    This fixture exists for explicit header passing in tests.
    """
    return {"X-API-KEY": "testing", "x-pytest-enabled": "1"}


@pytest.fixture
def no_auth_headers() -> dict[str, str]:
    """Headers without authentication for testing auth failures.

    Only includes the pytest header to skip queue publishing.
    """
    return {"x-pytest-enabled": "1"}


@pytest.fixture
async def unauthenticated_client(postgres_service: PostgresService) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Create async test client WITHOUT authentication headers.

    Use this to test endpoints that should reject unauthenticated requests.
    """
    from app import create_app

    app = create_app(
        psql_dsn=f"postgresql://{postgres_service.user}:{postgres_service.password}@{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
    )
    async with AsyncTestClient(app=app) as client:
        # Only include pytest header, NO X-API-KEY
        client.headers.update({"x-pytest-enabled": "1"})
        yield client
