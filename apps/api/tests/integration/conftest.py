"""Integration test fixtures.

The test_client fixture from root conftest.py is already configured with
auth headers. This file provides additional fixtures for integration tests.
"""

import pytest


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
