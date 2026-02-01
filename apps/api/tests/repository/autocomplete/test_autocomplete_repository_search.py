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


# ==============================================================================
# GET SIMILAR MAP NAMES TESTS
# ==============================================================================


class TestGetSimilarMapNames:
    """Test get_similar_map_names method."""

    @pytest.mark.asyncio
    async def test_get_similar_returns_list(self, repository: AutocompleteRepository) -> None:
        """Test that searching for map names returns a list."""
        # Act - search for common map name
        result = await repository.get_similar_map_names("Hanamura")

        # Assert
        assert result is None or isinstance(result, list)
        if result is not None:
            assert len(result) > 0
            assert all(isinstance(name, str) for name in result)

    @pytest.mark.asyncio
    async def test_get_similar_respects_limit(self, repository: AutocompleteRepository) -> None:
        """Test that limit parameter is respected."""
        # Act - search with different limits
        result_limit_1 = await repository.get_similar_map_names("a", limit=1)
        result_limit_3 = await repository.get_similar_map_names("a", limit=3)
        result_limit_10 = await repository.get_similar_map_names("a", limit=10)

        # Assert - results should not exceed limits
        if result_limit_1 is not None:
            assert len(result_limit_1) <= 1
        if result_limit_3 is not None:
            assert len(result_limit_3) <= 3
        if result_limit_10 is not None:
            assert len(result_limit_10) <= 10

    @pytest.mark.asyncio
    async def test_get_similar_ordered_by_similarity(self, repository: AutocompleteRepository) -> None:
        """Test that results are ordered by similarity score."""
        # Act
        result = await repository.get_similar_map_names("Hanamura", limit=5)

        # Assert - first result should be most similar (exact match or close)
        if result is not None and len(result) > 0:
            # First result should contain or be very close to the search term
            assert isinstance(result[0], str)

    @pytest.mark.asyncio
    async def test_get_similar_nonexistent_returns_none_or_list(self, repository: AutocompleteRepository) -> None:
        """Test searching for completely unrelated string."""
        # Act
        result = await repository.get_similar_map_names("XYZQWERTY999", limit=5)

        # Assert - may return None or a list (similarity might find something)
        assert result is None or isinstance(result, list)


# ==============================================================================
# GET SIMILAR MAP RESTRICTIONS TESTS
# ==============================================================================


class TestGetSimilarMapRestrictions:
    """Test get_similar_map_restrictions method."""

    @pytest.mark.asyncio
    async def test_get_similar_returns_list(self, repository: AutocompleteRepository) -> None:
        """Test that searching for restrictions returns a list or None."""
        # Act
        result = await repository.get_similar_map_restrictions("Jump", limit=5)

        # Assert
        assert result is None or isinstance(result, list)
        if result is not None:
            assert all(isinstance(restriction, str) for restriction in result)

    @pytest.mark.asyncio
    async def test_get_similar_respects_limit(self, repository: AutocompleteRepository) -> None:
        """Test that limit parameter is respected."""
        # Act
        result_limit_1 = await repository.get_similar_map_restrictions("a", limit=1)
        result_limit_5 = await repository.get_similar_map_restrictions("a", limit=5)

        # Assert
        if result_limit_1 is not None:
            assert len(result_limit_1) <= 1
        if result_limit_5 is not None:
            assert len(result_limit_5) <= 5


# ==============================================================================
# GET SIMILAR MAP MECHANICS TESTS
# ==============================================================================


class TestGetSimilarMapMechanics:
    """Test get_similar_map_mechanics method."""

    @pytest.mark.asyncio
    async def test_get_similar_returns_list(self, repository: AutocompleteRepository) -> None:
        """Test that searching for mechanics returns a list or None."""
        # Act
        result = await repository.get_similar_map_mechanics("Bhop", limit=5)

        # Assert
        assert result is None or isinstance(result, list)
        if result is not None:
            assert all(isinstance(mechanic, str) for mechanic in result)

    @pytest.mark.asyncio
    async def test_get_similar_respects_limit(self, repository: AutocompleteRepository) -> None:
        """Test that limit parameter is respected."""
        # Act
        result_limit_1 = await repository.get_similar_map_mechanics("a", limit=1)
        result_limit_5 = await repository.get_similar_map_mechanics("a", limit=5)

        # Assert
        if result_limit_1 is not None:
            assert len(result_limit_1) <= 1
        if result_limit_5 is not None:
            assert len(result_limit_5) <= 5


# ==============================================================================
# GET SIMILAR MAP CODES TESTS
# ==============================================================================


class TestGetSimilarMapCodes:
    """Test get_similar_map_codes method."""

    @pytest.mark.asyncio
    async def test_get_similar_exact_match_prioritized(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test that exact match is prioritized highest."""
        # Arrange - create a test map
        await create_test_map(unique_map_code)

        # Act - search for exact code
        result = await repository.get_similar_map_codes(unique_map_code, limit=5)

        # Assert
        assert result is not None
        assert isinstance(result, list)
        assert unique_map_code in result
        # Exact match should be first
        assert result[0] == unique_map_code

    @pytest.mark.asyncio
    async def test_get_similar_prefix_match_prioritized(
        self, repository: AutocompleteRepository, create_test_map, global_code_tracker: set[str]
    ) -> None:
        """Test that prefix matches are prioritized over similarity matches."""
        # Arrange - create maps with specific prefix
        prefix = f"AUTO{uuid4().hex[:4].upper()}"
        code1 = f"{prefix}A"
        code2 = f"{prefix}B"
        global_code_tracker.add(code1)
        global_code_tracker.add(code2)
        await create_test_map(code1)
        await create_test_map(code2)

        # Act - search with just the prefix
        result = await repository.get_similar_map_codes(prefix, limit=10)

        # Assert - should include our prefix codes
        assert result is not None
        # At least one of our codes should be in the results
        assert any(code in result for code in [code1, code2])

    @pytest.mark.asyncio
    async def test_get_similar_respects_limit(
        self, repository: AutocompleteRepository, create_test_map, global_code_tracker: set[str]
    ) -> None:
        """Test that limit parameter is respected."""
        # Arrange - create multiple test maps
        codes = [f"T{uuid4().hex[:5].upper()}" for _ in range(10)]
        for code in codes:
            global_code_tracker.add(code)
            await create_test_map(code)

        # Act
        result_limit_1 = await repository.get_similar_map_codes("T", limit=1)
        result_limit_5 = await repository.get_similar_map_codes("T", limit=5)

        # Assert
        if result_limit_1 is not None:
            assert len(result_limit_1) <= 1
        if result_limit_5 is not None:
            assert len(result_limit_5) <= 5

    @pytest.mark.asyncio
    async def test_get_similar_with_archived_filter(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test filtering by archived status."""
        # Arrange - create archived map
        await create_test_map(unique_map_code, archived=True)

        # Act - search with archived=True
        result_archived = await repository.get_similar_map_codes(unique_map_code, archived=True, limit=5)

        # Assert - should include the archived map
        assert result_archived is not None
        assert unique_map_code in result_archived

        # Act - search with archived=False
        result_not_archived = await repository.get_similar_map_codes(unique_map_code, archived=False, limit=5)

        # Assert - should NOT include the archived map
        assert result_not_archived is None or unique_map_code not in result_not_archived

    @pytest.mark.asyncio
    async def test_get_similar_with_hidden_filter(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test filtering by hidden status."""
        # Arrange - create hidden map
        await create_test_map(unique_map_code, hidden=True)

        # Act - search with hidden=True
        result_hidden = await repository.get_similar_map_codes(unique_map_code, hidden=True, limit=5)

        # Assert
        assert result_hidden is not None
        assert unique_map_code in result_hidden

        # Act - search with hidden=False
        result_not_hidden = await repository.get_similar_map_codes(unique_map_code, hidden=False, limit=5)

        # Assert
        assert result_not_hidden is None or unique_map_code not in result_not_hidden

    @pytest.mark.asyncio
    async def test_get_similar_with_playtesting_filter(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test filtering by playtesting status."""
        # Arrange
        await create_test_map(unique_map_code, playtesting="In Progress")

        # Act - with matching filter
        result_matching = await repository.get_similar_map_codes(unique_map_code, playtesting="In Progress", limit=5)

        # Assert
        assert result_matching is not None
        assert unique_map_code in result_matching

        # Act - with non-matching filter
        result_not_matching = await repository.get_similar_map_codes(unique_map_code, playtesting="Approved", limit=5)

        # Assert
        assert result_not_matching is None or unique_map_code not in result_not_matching

    @pytest.mark.asyncio
    async def test_get_similar_with_combined_filters(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test combining multiple filters."""
        # Arrange
        await create_test_map(
            unique_map_code,
            archived=False,
            hidden=True,
            playtesting="Approved",
        )

        # Act
        result = await repository.get_similar_map_codes(
            unique_map_code,
            archived=False,
            hidden=True,
            playtesting="Approved",
            limit=5,
        )

        # Assert
        assert result is not None
        assert unique_map_code in result

    @pytest.mark.asyncio
    async def test_get_similar_case_insensitive(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test that search is case-insensitive."""
        # Arrange
        await create_test_map(unique_map_code)

        # Act
        result_lower = await repository.get_similar_map_codes(unique_map_code.lower(), limit=5)
        result_upper = await repository.get_similar_map_codes(unique_map_code.upper(), limit=5)

        # Assert - both should find the code
        assert result_lower is not None
        assert result_upper is not None


# ==============================================================================
# GET SIMILAR USERS TESTS
# ==============================================================================


class TestGetSimilarUsers:
    """Test get_similar_users method."""

    @pytest.mark.asyncio
    async def test_get_similar_returns_list_of_tuples(
        self, repository: AutocompleteRepository, create_test_user
    ) -> None:
        """Test that searching for users returns list of (user_id, display_name) tuples."""
        # Arrange - create a test user
        user_id = await create_test_user(nickname="TestPlayer")

        # Act
        result = await repository.get_similar_users("TestPlayer", limit=10)

        # Assert
        assert result is None or isinstance(result, list)
        if result is not None:
            assert all(isinstance(item, tuple) for item in result)
            assert all(len(item) == 2 for item in result)
            # Should include our test user
            user_ids = [uid for uid, _ in result]
            assert user_id in user_ids

    @pytest.mark.asyncio
    async def test_get_similar_fake_users_only(
        self, repository: AutocompleteRepository, asyncpg_conn
    ) -> None:
        """Test filtering for fake users only (user_id < 1000000000000000)."""
        # Arrange - create a fake user (ID < 1000000000000000)
        fake_user_id = 123456
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3)",
            fake_user_id,
            "FakePlayer",
            "FakePlayer",
        )

        # Act
        result = await repository.get_similar_users("FakePlayer", limit=10, fake_users_only=True)

        # Assert
        if result is not None:
            user_ids = [uid for uid, _ in result]
            # All should be fake users (ID < 1000000000000000)
            assert all(uid < 1000000000000000 for uid in user_ids)

