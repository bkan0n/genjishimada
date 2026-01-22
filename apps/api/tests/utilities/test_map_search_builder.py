"""Tests for MapSearchSQLSpecBuilder validation and query building logic.

Tests the builder's validation rules, CTE generation, and query construction.
"""

import pytest

from utilities.map_search import MapSearchFilters, MapSearchSQLSpecBuilder

# ruff: noqa: D102, D103, ANN001, ANN201


class TestMapSearchSQLSpecBuilder:
    """Tests for MapSearchSQLSpecBuilder validation and query building."""

    # =========================================================================
    # VALIDATION TESTS
    # =========================================================================

    def test_validate_rejects_exact_and_range_difficulty(self):
        """Test that combining exact difficulty with range raises ValueError."""
        filters = MapSearchFilters(
            difficulty_exact="Medium",
            difficulty_range_min="Easy",
        )

        with pytest.raises(ValueError, match="Cannot use exact difficulty with range-based filtering"):
            MapSearchSQLSpecBuilder(filters)

    def test_validate_rejects_both_creator_filters(self):
        """Test that using both creator_ids and creator_names raises ValueError."""
        filters = MapSearchFilters(
            creator_ids=[123],
            creator_names=["TestUser"],
        )

        with pytest.raises(ValueError, match="Cannot use creator_ids and creator_names simultaneously"):
            MapSearchSQLSpecBuilder(filters)

    def test_validate_accepts_valid_filters(self):
        """Test that valid filter combinations pass validation."""
        # Exact difficulty only
        filters1 = MapSearchFilters(difficulty_exact="Hard")
        builder1 = MapSearchSQLSpecBuilder(filters1)
        assert builder1 is not None

        # Range difficulty only
        filters2 = MapSearchFilters(
            difficulty_range_min="Easy",
            difficulty_range_max="Hard",
        )
        builder2 = MapSearchSQLSpecBuilder(filters2)
        assert builder2 is not None

        # Creator IDs only
        filters3 = MapSearchFilters(creator_ids=[123, 456])
        builder3 = MapSearchSQLSpecBuilder(filters3)
        assert builder3 is not None

        # Creator names only
        filters4 = MapSearchFilters(creator_names=["User1", "User2"])
        builder4 = MapSearchSQLSpecBuilder(filters4)
        assert builder4 is not None

    # =========================================================================
    # QUERY BUILDING TESTS
    # =========================================================================

    def test_build_query_with_tags(self):
        """Test that tags filter generates the correct CTE."""
        filters = MapSearchFilters(
            tags=["Other Heroes", "XP Based"],
            page_size=10,
            page_number=1,
        )
        builder = MapSearchSQLSpecBuilder(filters)
        query_result = builder.build()

        # Verify query contains tag-related SQL
        assert "limited_tags" in query_result.query
        assert "tag_links" in query_result.query
        assert "tags" in query_result.query
        # Verify parameters include tag names
        assert "Other Heroes" in query_result.args
        assert "XP Based" in query_result.args

    def test_build_query_with_sorting(self):
        """Test that sort keys generate correct ORDER BY clauses."""
        filters = MapSearchFilters(
            sort=["difficulty:desc", "code:asc"],
            page_size=10,
            page_number=1,
        )
        builder = MapSearchSQLSpecBuilder(filters)
        query_result = builder.build()

        # Verify ORDER BY clause contains expected columns
        assert "ORDER BY" in query_result.query
        assert "raw_difficulty" in query_result.query.lower() or "m.raw_difficulty" in query_result.query
        assert "DESC" in query_result.query
        assert "code" in query_result.query.lower() or "m.code" in query_result.query
        assert "ASC" in query_result.query
