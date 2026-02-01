"""Integration tests for Utilities v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import datetime as dt
from io import BytesIO
from typing import Literal

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_utilities,
]


class TestUploadImage:
    """POST /api/v4/utilities/image"""

    @pytest.mark.xfail(reason="BUG: S3 client requires R2_ACCOUNT_ID env var which is not set in test environment")
    async def test_happy_path(self, test_client):
        """Upload image returns CDN URL."""
        # Create fake image data
        image_data = b"fake-png-data-for-testing"
        file = BytesIO(image_data)

        response = await test_client.post(
            "/api/v4/utilities/image",
            files={"data": ("test.png", file, "image/png")},
        )

        assert response.status_code == 200
        data = response.text  # Returns plain text URL
        assert isinstance(data, str)
        assert len(data) > 0
        # CDN URL should be a valid URL string
        assert "http" in data.lower()

    async def test_requires_auth(self, unauthenticated_client):
        """Upload image without auth returns 401."""
        image_data = b"fake-png-data-for-testing"
        file = BytesIO(image_data)

        response = await unauthenticated_client.post(
            "/api/v4/utilities/image",
            files={"data": ("test.png", file, "image/png")},
        )

        assert response.status_code == 401

    async def test_missing_file_returns_400(self, test_client):
        """Upload image without file data returns 400."""
        response = await test_client.post(
            "/api/v4/utilities/image",
            json={},  # No file data
        )

        assert response.status_code == 400


class TestLogAnalytics:
    """POST /api/v4/utilities/log"""

    async def test_happy_path(self, test_client, create_test_user):
        """Log analytics returns 204."""
        user_id = await create_test_user()

        payload = {
            "command_name": "test_command",
            "user_id": user_id,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "namespace": {"key": "value"},
        }

        response = await test_client.post("/api/v4/utilities/log", json=payload)

        assert response.status_code == 204

    async def test_requires_auth(self, unauthenticated_client):
        """Log analytics without auth returns 401."""
        payload = {
            "command_name": "test_command",
            "user_id": 999999999,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "namespace": {"key": "value"},
        }

        response = await unauthenticated_client.post("/api/v4/utilities/log", json=payload)

        assert response.status_code == 401

    async def test_invalid_payload_returns_400(self, test_client):
        """Log analytics with missing required fields returns 400."""
        payload = {
            "command_name": "test_command",
            # Missing user_id, created_at, namespace
        }

        response = await test_client.post("/api/v4/utilities/log", json=payload)

        assert response.status_code == 400


class TestLogMapClick:
    """POST /api/v4/utilities/log-map-click"""

    async def test_happy_path(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Log map click returns 204."""
        code = unique_map_code
        await create_test_map(code=code)
        user_id = await create_test_user()

        payload = {
            "code": code,
            "ip_address": "192.168.1.1",
            "user_id": user_id,
            "source": "web",
        }

        response = await test_client.post("/api/v4/utilities/log-map-click", json=payload)

        assert response.status_code == 204

    async def test_without_user_id(self, test_client, create_test_map, unique_map_code):
        """Log map click without user_id returns 204."""
        code = unique_map_code
        await create_test_map(code=code)

        payload = {
            "code": code,
            "ip_address": "192.168.1.1",
            "user_id": None,
            "source": "bot",
        }

        response = await test_client.post("/api/v4/utilities/log-map-click", json=payload)

        assert response.status_code == 204

    async def test_requires_auth(self, unauthenticated_client):
        """Log map click without auth returns 401."""
        payload = {
            "code": "TEST01",
            "ip_address": "192.168.1.1",
            "user_id": None,
            "source": "web",
        }

        response = await unauthenticated_client.post("/api/v4/utilities/log-map-click", json=payload)

        assert response.status_code == 401

    async def test_invalid_map_code_format_returns_400(self, test_client):
        """Log map click with invalid code format returns 400."""
        payload = {
            "code": "invalid",  # Lowercase, too short for OverwatchCode pattern
            "ip_address": "192.168.1.1",
            "user_id": None,
            "source": "web",
        }

        response = await test_client.post("/api/v4/utilities/log-map-click", json=payload)

        assert response.status_code == 400

    async def test_invalid_source_returns_400(self, test_client):
        """Log map click with invalid source enum returns 400."""
        payload = {
            "code": "TEST01",
            "ip_address": "192.168.1.1",
            "user_id": None,
            "source": "invalid_source",  # Not "web" or "bot"
        }

        response = await test_client.post("/api/v4/utilities/log-map-click", json=payload)

        assert response.status_code == 400

    @pytest.mark.parametrize("source", ["web", "bot"])
    async def test_all_source_values(self, test_client, create_test_map, unique_map_code, source: Literal["web", "bot"]):
        """All source enum values work correctly."""
        code = unique_map_code
        await create_test_map(code=code)

        payload = {
            "code": code,
            "ip_address": "192.168.1.1",
            "user_id": None,
            "source": source,
        }

        response = await test_client.post("/api/v4/utilities/log-map-click", json=payload)

        assert response.status_code == 204


class TestGetLogMapClicks:
    """GET /api/v4/utilities/log-map-click"""

    async def test_happy_path(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Get log map clicks returns list with complete structure."""
        # Create a click first
        code = unique_map_code
        map_id = await create_test_map(code=code)
        user_id = await create_test_user()

        await test_client.post(
            "/api/v4/utilities/log-map-click",
            json={
                "code": code,
                "ip_address": "192.168.1.1",
                "user_id": user_id,
                "source": "web",
            },
        )

        response = await test_client.get("/api/v4/utilities/log-map-click")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0  # Should have at least the click we just created

        # Find the click we just created
        our_click = next((item for item in data if item.get("user_id") == user_id), None)
        assert our_click is not None

        # Validate complete response structure
        assert "id" in our_click
        assert "map_id" in our_click
        assert "user_id" in our_click
        assert "source" in our_click
        assert "user_agent" in our_click
        assert "ip_hash" in our_click
        assert "inserted_at" in our_click
        assert "day_bucket" in our_click

        # Validate field types and values
        assert isinstance(our_click["id"], (int, type(None)))
        assert our_click["map_id"] == map_id
        assert our_click["user_id"] == user_id
        assert our_click["source"] == "web"
        assert isinstance(our_click["user_agent"], (str, type(None)))
        assert isinstance(our_click["ip_hash"], (str, type(None)))
        assert isinstance(our_click["inserted_at"], str)  # ISO datetime string
        assert isinstance(our_click["day_bucket"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get log map clicks without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/utilities/log-map-click")

        assert response.status_code == 401
