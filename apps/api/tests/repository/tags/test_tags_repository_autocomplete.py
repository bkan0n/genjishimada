"""Tests for TagsRepository.autocomplete_tags operation."""

from __future__ import annotations

import pytest
from genjishimada_sdk.tags import TagsAutocompleteRequest

from repository.tags_repository import TagsRepository

pytestmark = [pytest.mark.domain_tags]

GUILD_ID = 100000000000000001
OWNER_ID = 200000000000000001


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide tags repository instance."""
    return TagsRepository(asyncpg_conn)


class TestAutocompleteHappyPath:
    async def test_autocomplete_returns_matching_names(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        await create_test_tag("autocomplete-test", "content", owner_id=OWNER_ID)
        filters = TagsAutocompleteRequest(guild_id=GUILD_ID, q="autocomplete")
        result = await repository.autocomplete_tags(filters)
        assert any("autocomplete" in name.lower() for name in result.items)

    async def test_autocomplete_empty_query_returns_empty(
        self,
        repository: TagsRepository,
    ) -> None:
        filters = TagsAutocompleteRequest(guild_id=GUILD_ID, q="  ")
        result = await repository.autocomplete_tags(filters)
        assert result.items == []
