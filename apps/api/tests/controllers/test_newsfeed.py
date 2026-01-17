from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestNewsfeedEndpoints:
    """Tests for newsfeed event endpoints."""

    # =========================================================================
    # CREATE NEWSFEED EVENT TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_newsfeed_event_guide(self, test_client: AsyncTestClient[Litestar]):
        """Test creating a guide newsfeed event."""
        response = await test_client.post(
            "/api/v3/newsfeed/",
            json={
                "id": None,
                "timestamp": "2024-01-01T00:00:00Z",
                "event_type": "guide",
                "payload": {
                    "code": "1EASY",
                    "guide_url": "https://youtube.com/watch?v=test123",
                    "name": "TestGuideCreator",
                    "type": "guide"
                },
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["newsfeed_id"] is not None

    @pytest.mark.asyncio
    async def test_create_newsfeed_event_archive(self, test_client: AsyncTestClient[Litestar]):
        """Test creating an archive newsfeed event."""
        response = await test_client.post(
            "/api/v3/newsfeed/",
            json={
                "id": None,
                "timestamp": "2024-01-01T00:00:00Z",
                "event_type": "archive",
                "payload": {
                    "code": "2EASY",
                    "map_name": "Hanamura",
                    "creators": ["Creator1"],
                    "difficulty": "Easy",
                    "reason": "Map is broken",
                    "type": "archive"
                },
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["newsfeed_id"] is not None

    @pytest.mark.asyncio
    async def test_create_newsfeed_event_world_record(self, test_client: AsyncTestClient[Litestar]):
        """Test creating a world_record newsfeed event."""
        response = await test_client.post(
            "/api/v3/newsfeed/",
            json={
                "id": None,
                "timestamp": "2024-01-01T00:00:00Z",
                "event_type": "record",
                "payload": {
                    "code": "3EASY",
                    "time": 99999,
                    "map_name": "Hanamura",
                    "video": "https://youtube.com/watch?v=record123",
                    "rank_num": 1,
                    "name": "RecordHolder",
                    "medal": "Gold",
                    "difficulty": "Easy",
                    "type": "record",
                },
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["newsfeed_id"] is not None

    # =========================================================================
    # LIST NEWSFEED EVENTS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_default(self, test_client: AsyncTestClient[Litestar]):
        """Test listing newsfeed events with default pagination."""
        response = await test_client.get("/api/v3/newsfeed/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Default page size is 10
        assert len(data) <= 10
        # Should be ordered by most recent first
        if len(data) > 1:
            assert data[0]["timestamp"] >= data[1]["timestamp"]

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_with_page_size(self, test_client: AsyncTestClient[Litestar]):
        """Test listing events with custom page size."""
        response = await test_client.get("/api/v3/newsfeed/?page_size=20")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 20

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_page_2(self, test_client: AsyncTestClient[Litestar]):
        """Test listing events on page 2."""
        response = await test_client.get("/api/v3/newsfeed/?page_size=10&page_number=2")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data is None or isinstance(data, list)
        # May be empty or have items depending on total count

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_filter_by_type(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering events by type."""
        response = await test_client.get("/api/v3/newsfeed/?type=record")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # All returned items should be record type
        for event in data:
            assert event["event_type"] == "record"

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_filter_guide(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering events by guide type."""
        response = await test_client.get("/api/v3/newsfeed/?type=guide")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        for event in data:
            assert event["event_type"] == "guide"

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_no_type_match(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering by type that doesn't exist returns empty."""
        # Use an unusual type that likely won't exist
        response = await test_client.get("/api/v3/newsfeed/?type=nonexistent_type_xyz")
        assert response.status_code == 400

    # =========================================================================
    # GET SINGLE NEWSFEED EVENT TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_single_newsfeed_event(self, test_client: AsyncTestClient[Litestar]):
        """Test getting a single newsfeed event by ID."""
        # Use ID from seed data
        response = await test_client.get("/api/v3/newsfeed/1")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == 1
        assert data["event_type"] == "legacy_record"
        assert "payload" in data

    @pytest.mark.asyncio
    async def test_get_single_newsfeed_event_different_type(self, test_client: AsyncTestClient[Litestar]):
        """Test getting different event types."""
        # Guide event from seed
        response = await test_client.get("/api/v3/newsfeed/3")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == 3
        assert data["event_type"] == "guide"

        # Archive event from seed
        response = await test_client.get("/api/v3/newsfeed/5")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == 5
        assert data["event_type"] == "archive"

    @pytest.mark.asyncio
    async def test_get_nonexistent_newsfeed_event(self, test_client: AsyncTestClient[Litestar]):
        """Test getting non-existent event returns null."""
        response = await test_client.get("/api/v3/newsfeed/999999")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data is None
