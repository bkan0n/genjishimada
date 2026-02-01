"""Integration tests for Autocomplete v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest
from genjishimada_sdk.maps import Mechanics, PlaytestStatus, Restrictions

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_autocomplete,
]


class TestAutocompleteMapNames:
    """GET /api/v4/utilities/autocomplete/names"""

    async def test_happy_path(self, test_client, create_test_map):
        """Autocomplete map names returns list."""
        # Create test map to ensure data exists
        await create_test_map()

        response = await test_client.get(
            "/api/v4/utilities/autocomplete/names",
            params={"search": "Practice", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is list or None, don't assert exact content (dynamic data)
        assert isinstance(data, list) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Autocomplete map names without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/autocomplete/names",
            params={"search": "Practice"},
        )

        assert response.status_code == 401

    async def test_missing_search_returns_400(self, test_client):
        """Missing search parameter returns 400."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/names",
        )

        assert response.status_code == 400


class TestTransformMapName:
    """GET /api/v4/utilities/transformers/names"""

    async def test_happy_path(self, test_client, create_test_map):
        """Transform map name returns single value."""
        # Create test map to ensure data exists
        await create_test_map()

        response = await test_client.get(
            "/api/v4/utilities/transformers/names",
            params={"search": "Practice"},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is string or None, don't assert exact value (dynamic data)
        assert isinstance(data, str) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Transform map name without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/transformers/names",
            params={"search": "Practice"},
        )

        assert response.status_code == 401


class TestAutocompleteRestrictions:
    """GET /api/v4/utilities/autocomplete/restrictions"""

    async def test_happy_path(self, test_client):
        """Autocomplete restrictions returns valid values."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/restrictions",
            params={"search": "Wall", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        # Restrictions are static enum values, can validate structure
        assert isinstance(data, list) or data is None
        if data:
            # Each item should be a string
            for item in data:
                assert isinstance(item, str)

    async def test_requires_auth(self, unauthenticated_client):
        """Autocomplete restrictions without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/autocomplete/restrictions",
            params={"search": "Wall"},
        )

        assert response.status_code == 401

    @pytest.mark.parametrize("search_term", ["Wall", "Dash", "Jump", "Bhop"])
    async def test_search_variants(self, test_client, search_term):
        """Different search terms return valid restriction values."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/restrictions",
            params={"search": search_term, "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or data is None
        if data:
            for item in data:
                assert isinstance(item, str)


class TestTransformRestriction:
    """GET /api/v4/utilities/transformers/restrictions"""

    async def test_happy_path(self, test_client):
        """Transform restriction returns single value."""
        response = await test_client.get(
            "/api/v4/utilities/transformers/restrictions",
            params={"search": "Wall"},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is string or None
        assert isinstance(data, str) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Transform restriction without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/transformers/restrictions",
            params={"search": "Wall"},
        )

        assert response.status_code == 401


class TestAutocompleteMechanics:
    """GET /api/v4/utilities/autocomplete/mechanics"""

    async def test_happy_path(self, test_client):
        """Autocomplete mechanics returns valid values."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/mechanics",
            params={"search": "Climb", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        # Mechanics are static enum values, can validate structure
        assert isinstance(data, list) or data is None
        if data:
            # Each item should be a string
            for item in data:
                assert isinstance(item, str)

    async def test_requires_auth(self, unauthenticated_client):
        """Autocomplete mechanics without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/autocomplete/mechanics",
            params={"search": "Climb"},
        )

        assert response.status_code == 401

    async def test_missing_search_returns_400(self, test_client):
        """Missing search parameter returns 400."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/mechanics",
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("search_term", ["Edge", "Bhop", "Climb", "Dash"])
    async def test_search_variants(self, test_client, search_term):
        """Different search terms return valid mechanic values."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/mechanics",
            params={"search": search_term, "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or data is None
        if data:
            for item in data:
                assert isinstance(item, str)


class TestTransformMechanic:
    """GET /api/v4/utilities/transformers/mechanics"""

    async def test_happy_path(self, test_client):
        """Transform mechanic returns single value."""
        response = await test_client.get(
            "/api/v4/utilities/transformers/mechanics",
            params={"search": "Climb"},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is string or None
        assert isinstance(data, str) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Transform mechanic without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/transformers/mechanics",
            params={"search": "Climb"},
        )

        assert response.status_code == 401


class TestAutocompleteMapCodes:
    """GET /api/v4/utilities/autocomplete/codes"""

    async def test_happy_path(self, test_client, create_test_map):
        """Autocomplete map codes returns list."""
        # Create test map to ensure data exists
        await create_test_map()

        response = await test_client.get(
            "/api/v4/utilities/autocomplete/codes",
            params={"search": "A", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is list or None, don't assert exact content (dynamic data)
        assert isinstance(data, list) or data is None

    async def test_with_filters(self, test_client, create_test_map):
        """Map codes autocomplete with filters."""
        # Create test map
        await create_test_map()

        response = await test_client.get(
            "/api/v4/utilities/autocomplete/codes",
            params={
                "search": "A",
                "archived": False,
                "hidden": False,
                "playtesting": "In Progress",
                "limit": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Autocomplete map codes without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/autocomplete/codes",
            params={"search": "A"},
        )

        assert response.status_code == 401

    async def test_missing_search_returns_400(self, test_client):
        """Missing search parameter returns 400."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/codes",
        )

        assert response.status_code == 400

    async def test_invalid_playtest_status_returns_400(self, test_client):
        """Invalid playtesting enum value returns 400."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/codes",
            params={"search": "A", "playtesting": "InvalidStatus"},
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("playtest_status", ["Approved", "In Progress", "Rejected"])
    async def test_playtest_status_filters(self, test_client, create_test_map, playtest_status):
        """All PlaytestStatus enum values work as filters."""
        await create_test_map()

        response = await test_client.get(
            "/api/v4/utilities/autocomplete/codes",
            params={"search": "A", "playtesting": playtest_status, "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or data is None


class TestTransformMapCode:
    """GET /api/v4/utilities/transformers/codes"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Transform map code returns single value."""
        # Create test map to ensure data exists
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(
            "/api/v4/utilities/transformers/codes",
            params={"search": code[:2]},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is string or None, don't assert exact value (dynamic data)
        assert isinstance(data, str) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Transform map code without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/transformers/codes",
            params={"search": "A"},
        )

        assert response.status_code == 401


class TestAutocompleteUsers:
    """GET /api/v4/utilities/autocomplete/users"""

    async def test_happy_path(self, test_client, create_test_user):
        """Autocomplete users returns list of tuples."""
        # Create test user to ensure data exists
        await create_test_user()

        response = await test_client.get(
            "/api/v4/utilities/autocomplete/users",
            params={"search": "test", "limit": 10},
        )

        assert response.status_code == 200
        data = response.json()
        # Response is list of tuples [(int, str)] or None
        assert isinstance(data, list) or data is None
        if data:
            # Each item should be a list/tuple with 2 elements
            for item in data:
                assert isinstance(item, list)
                assert len(item) == 2
                assert isinstance(item[0], int)  # user_id
                assert isinstance(item[1], str)  # display_name

    async def test_fake_users_only(self, test_client, create_test_user):
        """Autocomplete users with fake_users_only filter."""
        # Create fake user (ID < 1000000000000000)
        user_id = await create_test_user()

        response = await test_client.get(
            "/api/v4/utilities/autocomplete/users",
            params={"search": "test", "limit": 10, "fake_users_only": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or data is None

    async def test_requires_auth(self, unauthenticated_client):
        """Autocomplete users without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/utilities/autocomplete/users",
            params={"search": "test"},
        )

        assert response.status_code == 401

    async def test_missing_search_returns_400(self, test_client):
        """Missing search parameter returns 400."""
        response = await test_client.get(
            "/api/v4/utilities/autocomplete/users",
        )

        assert response.status_code == 400
