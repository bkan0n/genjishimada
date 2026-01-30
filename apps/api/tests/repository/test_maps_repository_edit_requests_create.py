"""Tests for MapsRepository edit request create operations.

Test Coverage:
- create_edit_request: Create new edit request with validation
"""

import pytest
from faker import Faker

from repository.exceptions import ForeignKeyViolationError
from repository.maps_repository import MapsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_maps,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide maps repository instance."""
    return MapsRepository(asyncpg_conn)


# ==============================================================================
# CREATE EDIT REQUEST TESTS
# ==============================================================================


class TestCreateEditRequest:
    """Test creating edit requests."""

    # Tests will be added here
    pass
