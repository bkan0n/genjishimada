"""Tests for AutocompleteRepository edge cases.

Test Coverage:
- Empty string searches
- Special characters in search strings
- Case sensitivity handling
- Limit boundary conditions (0, 1, very large)
- Filter combinations
- Concurrent searches
- Null/None handling
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
