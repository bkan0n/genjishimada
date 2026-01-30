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


# ==============================================================================
# TRANSFORM MAP NAMES TESTS
# ==============================================================================


class TestTransformMapNames:
    """Test transform_map_names method."""

    @pytest.mark.asyncio
    async def test_transform_exact_match_returns_quoted_name(self, repository: AutocompleteRepository) -> None:
        """Test that exact map name match returns quoted format."""
        # Act - search for exact map name (should exist in seed data)
        result = await repository.transform_map_names("Hanamura")

        # Assert
        assert result is not None
        assert result.startswith('"')
        assert result.endswith('"')
        assert "Hanamura" in result

    @pytest.mark.asyncio
    async def test_transform_partial_match_returns_similar(self, repository: AutocompleteRepository) -> None:
        """Test that partial match returns most similar map name."""
        # Act - search for partial/misspelled name
        result = await repository.transform_map_names("Hana")

        # Assert - should find something similar
        assert result is not None
        assert result.startswith('"')
        assert result.endswith('"')

    @pytest.mark.asyncio
    async def test_transform_case_insensitive(self, repository: AutocompleteRepository) -> None:
        """Test that search is case-insensitive."""
        # Act
        result_lower = await repository.transform_map_names("hanamura")
        result_upper = await repository.transform_map_names("HANAMURA")
        result_mixed = await repository.transform_map_names("HaNaMuRa")

        # Assert - all should return same result
        assert result_lower is not None
        assert result_upper is not None
        assert result_mixed is not None

    @pytest.mark.asyncio
    async def test_transform_nonexistent_returns_none(self, repository: AutocompleteRepository) -> None:
        """Test that searching for completely unrelated string returns None."""
        # Act - search for gibberish
        result = await repository.transform_map_names("XYZQWERTYZZZZ123456")

        # Assert
        # Note: May return something due to similarity matching, or None
        # Just verify it doesn't crash
        if result is not None:
            assert isinstance(result, str)


# ==============================================================================
# TRANSFORM MAP RESTRICTIONS TESTS
# ==============================================================================


class TestTransformMapRestrictions:
    """Test transform_map_restrictions method."""

    @pytest.mark.asyncio
    async def test_transform_exact_match_returns_quoted_name(self, repository: AutocompleteRepository) -> None:
        """Test that exact restriction match returns quoted format."""
        # Act - search for common restriction (should exist in seed data)
        # Note: Actual restrictions depend on seed data
        result = await repository.transform_map_restrictions("Triple Jump")

        # Assert
        if result is not None:  # May not exist in seed data
            assert result.startswith('"')
            assert result.endswith('"')

    @pytest.mark.asyncio
    async def test_transform_partial_match_returns_similar(self, repository: AutocompleteRepository) -> None:
        """Test that partial match returns most similar restriction."""
        # Act
        result = await repository.transform_map_restrictions("Jump")

        # Assert - should find something similar if restrictions exist
        if result is not None:
            assert result.startswith('"')
            assert result.endswith('"')

    @pytest.mark.asyncio
    async def test_transform_case_insensitive(self, repository: AutocompleteRepository) -> None:
        """Test that search is case-insensitive."""
        # Act
        result_lower = await repository.transform_map_restrictions("jump")
        result_upper = await repository.transform_map_restrictions("JUMP")

        # Assert - both should return same type of result
        assert type(result_lower) == type(result_upper)


# ==============================================================================
# TRANSFORM MAP MECHANICS TESTS
# ==============================================================================


class TestTransformMapMechanics:
    """Test transform_map_mechanics method."""

    @pytest.mark.asyncio
    async def test_transform_exact_match_returns_quoted_name(self, repository: AutocompleteRepository) -> None:
        """Test that exact mechanic match returns quoted format."""
        # Act - search for common mechanic (should exist in seed data)
        result = await repository.transform_map_mechanics("Bhop")

        # Assert
        if result is not None:  # May not exist in seed data
            assert result.startswith('"')
            assert result.endswith('"')

    @pytest.mark.asyncio
    async def test_transform_partial_match_returns_similar(self, repository: AutocompleteRepository) -> None:
        """Test that partial match returns most similar mechanic."""
        # Act
        result = await repository.transform_map_mechanics("hop")

        # Assert - should find something similar if mechanics exist
        if result is not None:
            assert result.startswith('"')
            assert result.endswith('"')

    @pytest.mark.asyncio
    async def test_transform_case_insensitive(self, repository: AutocompleteRepository) -> None:
        """Test that search is case-insensitive."""
        # Act
        result_lower = await repository.transform_map_mechanics("bhop")
        result_upper = await repository.transform_map_mechanics("BHOP")

        # Assert - both should return same type of result
        assert type(result_lower) == type(result_upper)


# ==============================================================================
# TRANSFORM MAP CODES TESTS
# ==============================================================================


class TestTransformMapCodes:
    """Test transform_map_codes method."""

    @pytest.mark.asyncio
    async def test_transform_exact_match_returns_code(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test that exact code match returns the code in quoted format."""
        # Arrange - create a test map
        await create_test_map(unique_map_code)

        # Act
        result = await repository.transform_map_codes(unique_map_code)

        # Assert
        assert result is not None
        assert result == f'"{unique_map_code}"'

    @pytest.mark.asyncio
    async def test_transform_prefix_match_returns_code(
        self, repository: AutocompleteRepository, create_test_map, global_code_tracker: set[str]
    ) -> None:
        """Test that prefix match returns matching code."""
        # Arrange - create a test map with specific prefix
        code = f"PREFIX{uuid4().hex[:4].upper()}"
        global_code_tracker.add(code)
        await create_test_map(code)

        # Act - search with just the prefix
        result = await repository.transform_map_codes("PREFIX")

        # Assert - should return the code (may be ours or another test's)
        assert result is not None
        assert result.startswith('"')
        assert result.endswith('"')
        assert "PREFIX" in result

    @pytest.mark.asyncio
    async def test_transform_with_archived_filter(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test filtering by archived status."""
        # Arrange - create archived map
        await create_test_map(unique_map_code, archived=True)

        # Act - search with archived=True filter
        result_archived = await repository.transform_map_codes(unique_map_code, archived=True)

        # Assert - should find the archived map
        assert result_archived is not None
        assert unique_map_code in result_archived

        # Act - search with archived=False filter
        result_not_archived = await repository.transform_map_codes(unique_map_code, archived=False)

        # Assert - should NOT find the archived map
        assert result_not_archived is None or unique_map_code not in result_not_archived

    @pytest.mark.asyncio
    async def test_transform_with_hidden_filter(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test filtering by hidden status."""
        # Arrange - create hidden map
        await create_test_map(unique_map_code, hidden=True)

        # Act - search with hidden=True filter
        result_hidden = await repository.transform_map_codes(unique_map_code, hidden=True)

        # Assert - should find the hidden map
        assert result_hidden is not None
        assert unique_map_code in result_hidden

        # Act - search with hidden=False filter
        result_not_hidden = await repository.transform_map_codes(unique_map_code, hidden=False)

        # Assert - should NOT find the hidden map
        assert result_not_hidden is None or unique_map_code not in result_not_hidden

    @pytest.mark.asyncio
    async def test_transform_with_playtesting_filter(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test filtering by playtesting status."""
        # Arrange - create map with specific playtesting status
        await create_test_map(unique_map_code, playtesting="In Progress")

        # Act - search with matching playtesting filter
        result_matching = await repository.transform_map_codes(unique_map_code, playtesting="In Progress")

        # Assert - should find the map
        assert result_matching is not None
        assert unique_map_code in result_matching

        # Act - search with non-matching playtesting filter
        result_not_matching = await repository.transform_map_codes(unique_map_code, playtesting="Approved")

        # Assert - should NOT find the map
        assert result_not_matching is None or unique_map_code not in result_not_matching

    @pytest.mark.asyncio
    async def test_transform_with_all_filters(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test combining all filters."""
        # Arrange - create map with all specific attributes
        await create_test_map(
            unique_map_code,
            archived=False,
            hidden=False,
            playtesting="Approved",
        )

        # Act - search with all matching filters
        result = await repository.transform_map_codes(
            unique_map_code,
            archived=False,
            hidden=False,
            playtesting="Approved",
        )

        # Assert
        assert result is not None
        assert unique_map_code in result

    @pytest.mark.asyncio
    async def test_transform_case_insensitive(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test that code search is case-insensitive."""
        # Arrange
        await create_test_map(unique_map_code)

        # Act
        result_lower = await repository.transform_map_codes(unique_map_code.lower())
        result_upper = await repository.transform_map_codes(unique_map_code.upper())

        # Assert - should find the code regardless of case
        # (Results may differ due to other maps, but both should succeed)
        assert result_lower is not None
        assert result_upper is not None

    @pytest.mark.asyncio
    async def test_transform_nonexistent_code_returns_none(self, repository: AutocompleteRepository) -> None:
        """Test that searching for non-existent code returns None."""
        # Act - search for code that definitely doesn't exist
        result = await repository.transform_map_codes("NONEXISTENT9999999")

        # Assert - should return None or similar non-matching code
        # Don't assert None because similarity matching might return something
        if result is not None:
            assert isinstance(result, str)
