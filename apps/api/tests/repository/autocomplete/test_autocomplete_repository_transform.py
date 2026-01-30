"""Tests for AutocompleteRepository transform operations.

Test Coverage:
- transform_map_names: Happy path, no match, format verification
- transform_map_restrictions: Happy path, no match, format verification
- transform_map_mechanics: Happy path, no match, format verification
- transform_map_codes: Happy path, filters, no match, format verification
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
