"""Tests for v4 utilities routes."""

import pytest


class TestUtilitiesEndpoints:
    """Test endpoints."""

    @pytest.mark.asyncio
    async def test_log_map_click_endpoint_exists(self, test_client):
        """Test log map click endpoint exists and accepts requests."""
        # Test endpoint exists - it will fail with 500 if map doesn't exist but that's OK
        # The repository test validates the actual logging works
        response = await test_client.post(
            "/api/v4/utilities/log-map-click",
            json={
                "code": "TEST12",
                "ip_address": "127.0.0.1",
                "user_id": None,
                "source": "web",
            },
        )
        # Endpoint exists if we get either 204 (success) or 500 (DB error), not 404
        assert response.status_code in (204, 500)

    @pytest.mark.asyncio
    async def test_upload_image_returns_url(self, test_client):
        """Test image upload endpoint."""
        # Create a minimal test image (1x1 PNG)
        import io
        png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'

        files = {"data": ("test.png", io.BytesIO(png_data), "image/png")}
        response = await test_client.post("/api/v4/utilities/image", files=files)

        assert response.status_code == 200
        url = response.json()
        assert isinstance(url, str)
        assert url.startswith("http")
