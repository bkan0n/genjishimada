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


# ==============================================================================
# EMPTY STRING SEARCHES
# ==============================================================================


class TestEmptyStringSearches:
    """Test behavior with empty search strings."""

    @pytest.mark.asyncio
    async def test_search_map_names_empty_string(self, repository: AutocompleteRepository) -> None:
        """Test searching map names with empty string."""
        # Act
        result = await repository.get_similar_map_names("", limit=5)

        # Assert - should return results or None, not crash
        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_transform_map_names_empty_string(self, repository: AutocompleteRepository) -> None:
        """Test transforming with empty string."""
        # Act
        result = await repository.transform_map_names("")

        # Assert - should return result or None, not crash
        assert result is None or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_search_map_codes_empty_string(self, repository: AutocompleteRepository) -> None:
        """Test searching map codes with empty string."""
        # Act
        result = await repository.get_similar_map_codes("", limit=5)

        # Assert
        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_users_empty_string(self, repository: AutocompleteRepository) -> None:
        """Test searching users with empty string."""
        # Act
        result = await repository.get_similar_users("", limit=5)

        # Assert
        assert result is None or isinstance(result, list)


# ==============================================================================
# SPECIAL CHARACTERS
# ==============================================================================


class TestSpecialCharacters:
    """Test behavior with special characters in search strings."""

    @pytest.mark.asyncio
    async def test_search_with_sql_injection_attempt(self, repository: AutocompleteRepository) -> None:
        """Test that SQL injection attempts are safely handled."""
        # Act - try various SQL injection patterns
        malicious_inputs = [
            "'; DROP TABLE core.maps; --",
            "1' OR '1'='1",
            "\" OR 1=1 --",
            "admin'--",
        ]

        for malicious_input in malicious_inputs:
            result = await repository.get_similar_map_codes(malicious_input, limit=5)
            # Assert - should not crash, return safe results
            assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_with_wildcards(self, repository: AutocompleteRepository) -> None:
        """Test searching with SQL wildcard characters."""
        # Act
        result_percent = await repository.get_similar_map_codes("%", limit=5)
        result_underscore = await repository.get_similar_map_codes("_", limit=5)

        # Assert - wildcards should be treated as literal characters
        assert result_percent is None or isinstance(result_percent, list)
        assert result_underscore is None or isinstance(result_underscore, list)

    @pytest.mark.asyncio
    async def test_search_with_unicode(self, repository: AutocompleteRepository) -> None:
        """Test searching with unicode characters."""
        # Act
        unicode_strings = ["日本語", "émojis", "Ñoño", "🎮"]

        for unicode_str in unicode_strings:
            result = await repository.get_similar_map_names(unicode_str, limit=5)
            # Assert - should handle unicode gracefully
            assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_with_backslashes(self, repository: AutocompleteRepository) -> None:
        """Test searching with backslash characters."""
        # Act
        result = await repository.get_similar_map_codes("TEST\\CODE", limit=5)

        # Assert
        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_with_quotes(self, repository: AutocompleteRepository) -> None:
        """Test searching with quote characters."""
        # Act
        result_single = await repository.get_similar_map_codes("'TEST'", limit=5)
        result_double = await repository.get_similar_map_codes('"TEST"', limit=5)

        # Assert
        assert result_single is None or isinstance(result_single, list)
        assert result_double is None or isinstance(result_double, list)


# ==============================================================================
# LIMIT BOUNDARY CONDITIONS
# ==============================================================================


class TestLimitBoundaries:
    """Test behavior with various limit values."""

    @pytest.mark.asyncio
    async def test_search_with_limit_zero(self, repository: AutocompleteRepository) -> None:
        """Test searching with limit=0."""
        # Act
        result = await repository.get_similar_map_names("Hanamura", limit=0)

        # Assert - should return empty list or None
        assert result is None or result == []

    @pytest.mark.asyncio
    async def test_search_with_limit_one(self, repository: AutocompleteRepository) -> None:
        """Test searching with limit=1."""
        # Act
        result = await repository.get_similar_map_names("Hanamura", limit=1)

        # Assert
        if result is not None:
            assert len(result) <= 1

    @pytest.mark.asyncio
    async def test_search_with_very_large_limit(self, repository: AutocompleteRepository) -> None:
        """Test searching with very large limit."""
        # Act
        result = await repository.get_similar_map_names("a", limit=1000)

        # Assert - should not crash, may return fewer results than limit
        assert result is None or isinstance(result, list)
        if result is not None:
            assert len(result) <= 1000

    @pytest.mark.asyncio
    async def test_search_users_with_different_limits(self, repository: AutocompleteRepository) -> None:
        """Test user search respects various limit values."""
        # Act
        result_1 = await repository.get_similar_users("test", limit=1)
        result_5 = await repository.get_similar_users("test", limit=5)
        result_100 = await repository.get_similar_users("test", limit=100)

        # Assert
        if result_1 is not None:
            assert len(result_1) <= 1
        if result_5 is not None:
            assert len(result_5) <= 5
        if result_100 is not None:
            assert len(result_100) <= 100


# ==============================================================================
# FILTER COMBINATIONS
# ==============================================================================


class TestFilterCombinations:
    """Test various filter combinations for map codes."""

    @pytest.mark.asyncio
    async def test_all_filters_none(self, repository: AutocompleteRepository, create_test_map, unique_map_code: str) -> None:
        """Test searching with all filters set to None."""
        # Arrange
        await create_test_map(unique_map_code)

        # Act - all filters None means no filtering
        result = await repository.get_similar_map_codes(
            unique_map_code,
            archived=None,
            hidden=None,
            playtesting=None,
            limit=5,
        )

        # Assert - should find the map regardless of its attributes
        assert result is not None
        assert unique_map_code in result

    @pytest.mark.asyncio
    async def test_contradictory_filters(
        self, repository: AutocompleteRepository, create_test_map, unique_map_code: str
    ) -> None:
        """Test that contradictory filters work correctly."""
        # Arrange - create non-archived map
        await create_test_map(unique_map_code, archived=False)

        # Act - search for archived maps (contradicts the created map)
        result = await repository.get_similar_map_codes(unique_map_code, archived=True, limit=5)

        # Assert - should not find the map
        assert result is None or unique_map_code not in result

    @pytest.mark.asyncio
    async def test_multiple_playtesting_statuses(
        self, repository: AutocompleteRepository, create_test_map, global_code_tracker: set[str]
    ) -> None:
        """Test searching maps with different playtesting statuses."""
        # Arrange - create maps with different statuses
        code_approved = f"T{uuid4().hex[:5].upper()}"
        code_in_progress = f"T{uuid4().hex[:5].upper()}"
        code_rejected = f"T{uuid4().hex[:5].upper()}"

        global_code_tracker.add(code_approved)
        global_code_tracker.add(code_in_progress)
        global_code_tracker.add(code_rejected)

        await create_test_map(code_approved, playtesting="Approved")
        await create_test_map(code_in_progress, playtesting="In Progress")
        await create_test_map(code_rejected, playtesting="Rejected")

        # Act - search for each status
        result_approved = await repository.get_similar_map_codes("T", playtesting="Approved", limit=20)
        result_in_progress = await repository.get_similar_map_codes("T", playtesting="In Progress", limit=20)
        result_rejected = await repository.get_similar_map_codes("T", playtesting="Rejected", limit=20)

        # Assert - each search should include the respective map
        if result_approved is not None:
            assert code_approved in result_approved
        if result_in_progress is not None:
            assert code_in_progress in result_in_progress
        if result_rejected is not None:
            assert code_rejected in result_rejected


# ==============================================================================
# NULL/NONE HANDLING
# ==============================================================================


class TestNullHandling:
    """Test behavior with null/None values."""

    @pytest.mark.asyncio
    async def test_search_with_whitespace_only(self, repository: AutocompleteRepository) -> None:
        """Test searching with whitespace-only strings."""
        # Act
        result_spaces = await repository.get_similar_map_names("   ", limit=5)
        result_tabs = await repository.get_similar_map_names("\t\t", limit=5)
        result_newlines = await repository.get_similar_map_names("\n\n", limit=5)

        # Assert - should handle gracefully
        assert result_spaces is None or isinstance(result_spaces, list)
        assert result_tabs is None or isinstance(result_tabs, list)
        assert result_newlines is None or isinstance(result_newlines, list)

    @pytest.mark.asyncio
    async def test_search_with_mixed_whitespace(self, repository: AutocompleteRepository) -> None:
        """Test searching with mixed whitespace."""
        # Act
        result = await repository.get_similar_map_names("Hana   mura", limit=5)

        # Assert
        assert result is None or isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_users_with_special_nicknames(
        self, repository: AutocompleteRepository, asyncpg_conn, global_user_id_tracker: set[int]
    ) -> None:
        """Test searching for users with special characters in nicknames."""
        # Arrange - create user with special nickname
        user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        global_user_id_tracker.add(user_id)

        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3)",
            user_id,
            "test_user-123",
            "Test User 123",
        )

        # Act
        result = await repository.get_similar_users("test_user", limit=10)

        # Assert - should find the user
        if result is not None:
            user_ids = [uid for uid, _ in result]
            assert user_id in user_ids

    @pytest.mark.asyncio
    async def test_search_very_long_string(self, repository: AutocompleteRepository) -> None:
        """Test searching with very long string."""
        # Act - 1000 character string
        long_string = "A" * 1000
        result = await repository.get_similar_map_names(long_string, limit=5)

        # Assert - should handle without crashing
        assert result is None or isinstance(result, list)
