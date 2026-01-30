"""Tests for AutocompleteRepository search operations.

Test Coverage:
- get_similar_map_names: Happy path, empty results, limit parameter
- get_similar_map_restrictions: Happy path, empty results, limit parameter
- get_similar_map_mechanics: Happy path, empty results, limit parameter
- get_similar_map_codes: Happy path, filters, priority ordering
- get_similar_users: Happy path, filters, name aggregation
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.autocomplete_repository import AutocompleteRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_autocomplete,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide autocomplete repository instance."""
    return AutocompleteRepository(asyncpg_conn)


# Tests will go here
