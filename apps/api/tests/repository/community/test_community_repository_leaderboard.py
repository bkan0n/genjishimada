"""Tests for CommunityRepository.fetch_community_leaderboard method."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.community_repository import CommunityRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_community,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide community repository instance."""
    return CommunityRepository(asyncpg_conn)


# Tests will go here
