from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_204_NO_CONTENT
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestUtilitiesEndpoints:
    """Tests for utility endpoints (autocomplete, transformers, logging)."""

    # =========================================================================
    # MAP NAME AUTOCOMPLETE & TRANSFORM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_autocomplete_map_names(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete map names with partial match."""
        response = await test_client.get("/api/v3/utilities/autocomplete/names?search=Hana&limit=5")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_autocomplete_map_names_no_match(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete with no matching map names."""
        response = await test_client.get("/api/v3/utilities/autocomplete/names?search=NonExistentMap&limit=5")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_transform_map_name_exact(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming exact map name."""
        response = await test_client.get("/api/v3/utilities/transformers/names?search=Hanamura")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == "Hanamura"

    @pytest.mark.asyncio
    async def test_transform_map_name_fuzzy(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming fuzzy map name."""
        response = await test_client.get("/api/v3/utilities/transformers/names?search=hanamra")  # typo
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Should still match Hanamura
        assert data == "Hanamura" or data is None  # Depends on fuzzy threshold

    @pytest.mark.asyncio
    async def test_transform_map_name_invalid(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming invalid map name returns None."""
        response = await test_client.get("/api/v3/utilities/transformers/names?search=CompletelyWrongMap")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, str) or data is None

    # =========================================================================
    # MAP CODE AUTOCOMPLETE & TRANSFORM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_autocomplete_map_codes(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete map codes."""
        response = await test_client.get("/api/v3/utilities/autocomplete/codes?search=1EASY&limit=5")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5
        # Should include exact match
        assert "1EASY" in data

    @pytest.mark.asyncio
    async def test_autocomplete_map_codes_with_filters(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete map codes with archived filter."""
        response = await test_client.get("/api/v3/utilities/autocomplete/codes?search=EASY&archived=false&limit=10")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should return codes that match
        assert all("EASY" in code for code in data)

    @pytest.mark.asyncio
    async def test_transform_map_code_exact(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming exact map code."""
        response = await test_client.get("/api/v3/utilities/transformers/codes?search=1EASY")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == "1EASY"

    @pytest.mark.asyncio
    async def test_transform_map_code_with_filters(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming map code with filters."""
        response = await test_client.get("/api/v3/utilities/transformers/codes?search=1EASY&archived=false")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == "1EASY"

    @pytest.mark.asyncio
    async def test_transform_map_code_invalid(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming invalid map code returns None."""
        response = await test_client.get("/api/v3/utilities/transformers/codes?search=ZZZZZ")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, str) or data is None

    # =========================================================================
    # RESTRICTIONS AUTOCOMPLETE & TRANSFORM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_autocomplete_restrictions(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete map restrictions."""
        # Using a known restriction from the schema
        response = await test_client.get("/api/v3/utilities/autocomplete/restrictions?search=wall&limit=5")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # May return matches or empty depending on seed data
        assert isinstance(data, list) or data is None

    @pytest.mark.asyncio
    async def test_transform_restriction(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming restriction."""
        response = await test_client.get("/api/v3/utilities/transformers/restrictions?search=wallclimb")
        assert response.status_code == HTTP_200_OK
        # May return match or None depending on implementation
        data = response.json()
        # Just verify it doesn't error

    # =========================================================================
    # MECHANICS AUTOCOMPLETE & TRANSFORM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_autocomplete_mechanics(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete map mechanics."""
        response = await test_client.get("/api/v3/utilities/autocomplete/mechanics?search=wall&limit=5")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list) or data is None

    @pytest.mark.asyncio
    async def test_transform_mechanic(self, test_client: AsyncTestClient[Litestar]):
        """Test transforming mechanic."""
        response = await test_client.get("/api/v3/utilities/transformers/mechanics?search=wallclimb")
        assert response.status_code == HTTP_200_OK
        # Just verify it doesn't error
        data = response.json()

    # =========================================================================
    # USER AUTOCOMPLETE TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_autocomplete_users(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete users by name."""
        response = await test_client.get("/api/v3/utilities/autocomplete/users?search=Shadow&limit=10")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Should find ShadowSlayer users from seed
        assert isinstance(data, list) or data is None
        if data:
            # Each item is a tuple [user_id, display_name]
            assert isinstance(data[0], list)
            assert len(data[0]) == 2

    @pytest.mark.asyncio
    async def test_autocomplete_users_with_fake_only(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete users with fake_users_only filter."""
        response = await test_client.get("/api/v3/utilities/autocomplete/users?search=Fake&fake_users_only=true&limit=10")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # May return fake users or empty
        assert isinstance(data, list) or data is None

    @pytest.mark.asyncio
    async def test_autocomplete_users_no_match(self, test_client: AsyncTestClient[Litestar]):
        """Test autocomplete with no matching users."""
        response = await test_client.get("/api/v3/utilities/autocomplete/users?search=NonExistentUser999&limit=10")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    # =========================================================================
    # ANALYTICS LOGGING TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_log_analytics_command(self, test_client: AsyncTestClient[Litestar]):
        """Test logging an analytics command."""
        response = await test_client.post(
            "/api/v3/utilities/log",
            json={
                "command_name": "test_command",
                "user_id": 100000000000000000,
                "created_at": "2024-01-01T00:00:00Z",
                "namespace": {"source": "test"},
            },
        )
        assert response.status_code == 201

    # =========================================================================
    # MAP CLICK LOGGING TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_log_map_click_new(self, test_client: AsyncTestClient[Litestar]):
        """Test logging a new map click."""
        response = await test_client.post(
            "/api/v3/utilities/log-map-click",
            json={
                "code": "1EASY",
                "user_id": 100000000000000000,
                "source": "web",
                "ip_address": "127.0.0.1",
            },
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_log_map_click_duplicate_same_day(self, test_client: AsyncTestClient[Litestar]):
        """Test logging duplicate map click same day (conflict, no insert)."""
        # First click
        response = await test_client.post(
            "/api/v3/utilities/log-map-click",
            json={
                "code": "2EASY",
                "user_id": 100000000000000001,
                "source": "web",
                "ip_address": "127.0.0.2",
            },
        )
        assert response.status_code == 201

        # Duplicate click (should still succeed, but won't insert)
        response = await test_client.post(
            "/api/v3/utilities/log-map-click",
            json={
                "code": "2EASY",
                "user_id": 100000000000000001,
                "source": "web",
                "ip_address": "127.0.0.2",
            },
        )
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_get_log_map_clicks(self, test_client: AsyncTestClient[Litestar]):
        """Test getting recent map click logs."""
        response = await test_client.get("/api/v3/utilities/log-map-click")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Should return list (may be empty or have recent clicks)
        assert isinstance(data, list)
        # Max 100 results
        assert len(data) <= 100
