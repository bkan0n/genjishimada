"""Tests for MapsRepository edit request update operations.

Test Coverage:
- set_edit_request_message_id: Set Discord message ID for edit request
- resolve_edit_request: Mark edit request as resolved (accepted/rejected)
"""

import pytest
from faker import Faker

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
# SET EDIT REQUEST MESSAGE ID TESTS
# ==============================================================================


class TestSetEditRequestMessageId:
    """Test setting Discord message ID."""

    # Tests will be added here
    pass


# ==============================================================================
# RESOLVE EDIT REQUEST TESTS
# ==============================================================================


class TestResolveEditRequest:
    """Test resolving edit requests."""

    # Tests will be added here
    pass
