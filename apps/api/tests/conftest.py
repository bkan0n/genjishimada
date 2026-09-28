"""Suite-wide policy; data and application fixtures live in support/."""

import hashlib

import pytest


@pytest.fixture
def faker_seed(request: pytest.FixtureRequest) -> int:
    """Stable within a case, independent of worker assignment or execution order."""
    return int.from_bytes(hashlib.sha256(request.node.nodeid.encode()).digest()[:8])


@pytest.fixture(autouse=True)
def _legacy_database_isolation(request: pytest.FixtureRequest) -> None:
    """Bridge old factory pools until feature suites use explicit dependencies."""
    if "postgres_service" in request.fixturenames:
        request.getfixturevalue("isolated_database")
