"""Tests for UtilitiesRepository edge cases and integration scenarios."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.utilities_repository import UtilitiesRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_utilities,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide utilities repository instance."""
    return UtilitiesRepository(asyncpg_conn)

# Tests will go here
