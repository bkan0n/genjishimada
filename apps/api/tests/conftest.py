"""Suite-wide policy; data and application fixtures live in support/."""

import hashlib

import pytest


@pytest.fixture
def faker_seed(request: pytest.FixtureRequest) -> int:
    """Stable within a case, independent of worker assignment or execution order."""
    return int.from_bytes(hashlib.sha256(request.node.nodeid.encode()).digest()[:8])
