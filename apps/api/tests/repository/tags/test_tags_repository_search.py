"""Tests for TagsRepository search operations."""

import pytest
from genjishimada_sdk.tags import TagsSearchFilters

from repository.tags_repository import TagsRepository

from .conftest import GUILD_ID

pytestmark = [
    pytest.mark.domain_tags,
]

OWNER_ID = 200000000000000001


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide tags repository instance."""
    return TagsRepository(asyncpg_conn)


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestSearchTagsHappyPath:
    """Test happy path scenarios for search_tags."""

    async def test_search_returns_existing_tag_by_name(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        """Test that search_tags finds a tag by exact name."""
        await create_test_tag("search-test-alpha", "alpha content", owner_id=OWNER_ID)

        filters = TagsSearchFilters(guild_id=GUILD_ID, name="search-test-alpha")
        result = await repository.search_tags(filters)

        assert len(result.items) == 1
        assert result.items[0].name == "search-test-alpha"
        assert result.items[0].guild_id == GUILD_ID
        assert result.items[0].owner_id == OWNER_ID

    async def test_search_case_insensitive_exact(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        """Test that exact name search is case-insensitive."""
        await create_test_tag("CaseMix-Search", "case content", owner_id=OWNER_ID)

        filters = TagsSearchFilters(guild_id=GUILD_ID, name="casemix-search")
        result = await repository.search_tags(filters)

        assert len(result.items) == 1
        assert result.items[0].name == "CaseMix-Search"

    async def test_search_include_content_returns_content(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        """Test that include_content=True populates the content field."""
        await create_test_tag("content-tag-search", "this is the body", owner_id=OWNER_ID)

        filters = TagsSearchFilters(guild_id=GUILD_ID, name="content-tag-search", include_content=True)
        result = await repository.search_tags(filters)

        assert len(result.items) == 1
        assert result.items[0].content == "this is the body"

    async def test_search_without_include_content_returns_none(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        """Test that without include_content, content is None."""
        await create_test_tag("no-content-tag-search", "hidden body", owner_id=OWNER_ID)

        filters = TagsSearchFilters(guild_id=GUILD_ID, name="no-content-tag-search")
        result = await repository.search_tags(filters)

        assert len(result.items) == 1
        assert result.items[0].content is None

    async def test_search_limit_caps_results(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        """Test that limit parameter caps the number of returned results."""
        for i in range(5):
            await create_test_tag(f"limit-cap-tag-{i}", f"content {i}", owner_id=OWNER_ID)

        filters = TagsSearchFilters(guild_id=GUILD_ID, limit=2)
        result = await repository.search_tags(filters)

        assert len(result.items) <= 2

    async def test_search_nonexistent_name_returns_suggestions(
        self,
        repository: TagsRepository,
        create_test_tag,
    ) -> None:
        """Test that searching for a nonexistent name triggers fuzzy suggestions."""
        await create_test_tag("suggestion-source", "some content", owner_id=OWNER_ID)

        filters = TagsSearchFilters(guild_id=GUILD_ID, name="suggestin-sourc")
        result = await repository.search_tags(filters)

        assert len(result.items) == 0
        assert result.suggestions is not None
        assert "suggestion-source" in result.suggestions
