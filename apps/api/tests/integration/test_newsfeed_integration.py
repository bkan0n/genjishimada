"""Integration tests for Newsfeed v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import datetime as dt

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_newsfeed,
]


class TestCreateNewsfeedEvent:
    """POST /api/v3/newsfeed/"""

    async def test_happy_path(self, test_client):
        """Create newsfeed event returns job status and event ID."""
        payload = {
            "id": None,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": {
                "type": "announcement",
                "title": "Test Announcement",
                "content": "Test content for announcement",
            },
        }

        response = await test_client.post("/api/v3/newsfeed/", json=payload)

        assert response.status_code == 201
        data = response.json()
        # Should return PublishNewsfeedJobResponse structure
        assert "job_status" in data
        assert "newsfeed_id" in data
        assert isinstance(data["job_status"], dict)
        assert isinstance(data["newsfeed_id"], int)
        assert data["newsfeed_id"] > 0

    async def test_requires_auth(self, unauthenticated_client):
        """Create newsfeed event without auth returns 401."""
        payload = {
            "id": None,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": {
                "type": "announcement",
                "title": "Test",
                "content": "Test",
            },
        }

        response = await unauthenticated_client.post("/api/v3/newsfeed/", json=payload)

        assert response.status_code == 401

    async def test_invalid_payload_returns_400(self, test_client):
        """Create newsfeed event with missing required fields returns 400."""
        payload = {
            "id": None,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            # Missing payload field - required
        }

        response = await test_client.post("/api/v3/newsfeed/", json=payload)

        assert response.status_code == 400

    async def test_invalid_event_type_returns_400(self, test_client):
        """Create newsfeed event with invalid event type returns 400."""
        payload = {
            "id": None,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": {
                "type": "invalid_type",  # Not in NewsfeedEventType literal
                "title": "Test",
                "content": "Test",
            },
        }

        response = await test_client.post("/api/v3/newsfeed/", json=payload)

        assert response.status_code == 400

    async def test_create_and_retrieve_announcement(self, test_client):
        """Round-trip test: create announcement event and retrieve it."""
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "id": None,
            "timestamp": timestamp.isoformat(),
            "payload": {
                "type": "announcement",
                "title": "Round-trip Test Announcement",
                "content": "Testing round-trip for announcement type",
                "url": "https://example.com",
            },
        }

        # Create
        create_response = await test_client.post("/api/v3/newsfeed/", json=payload)
        assert create_response.status_code == 201
        created_data = create_response.json()
        newsfeed_id = created_data["newsfeed_id"]

        # Retrieve
        get_response = await test_client.get(f"/api/v3/newsfeed/{newsfeed_id}")
        assert get_response.status_code == 200
        retrieved_data = get_response.json()

        # Validate round-trip
        assert retrieved_data["id"] == newsfeed_id
        assert retrieved_data["payload"]["type"] == "announcement"
        assert retrieved_data["payload"]["title"] == "Round-trip Test Announcement"
        assert retrieved_data["payload"]["content"] == "Testing round-trip for announcement type"
        assert retrieved_data["payload"]["url"] == "https://example.com"

    async def test_create_and_retrieve_guide(self, test_client):
        """Round-trip test: create guide event and retrieve it."""
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "id": None,
            "timestamp": timestamp.isoformat(),
            "payload": {
                "type": "guide",
                "code": "ABC123",
                "guide_url": "https://youtube.com/watch?v=test",
                "name": "Test Guide Creator",
            },
        }

        # Create
        create_response = await test_client.post("/api/v3/newsfeed/", json=payload)
        assert create_response.status_code == 201
        created_data = create_response.json()
        newsfeed_id = created_data["newsfeed_id"]

        # Retrieve
        get_response = await test_client.get(f"/api/v3/newsfeed/{newsfeed_id}")
        assert get_response.status_code == 200
        retrieved_data = get_response.json()

        # Validate round-trip
        assert retrieved_data["id"] == newsfeed_id
        assert retrieved_data["payload"]["type"] == "guide"
        assert retrieved_data["payload"]["code"] == "ABC123"
        assert retrieved_data["payload"]["guide_url"] == "https://youtube.com/watch?v=test"
        assert retrieved_data["payload"]["name"] == "Test Guide Creator"

    async def test_create_and_retrieve_role(self, test_client):
        """Round-trip test: create role event and retrieve it."""
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "id": None,
            "timestamp": timestamp.isoformat(),
            "payload": {
                "type": "role",
                "user_id": 12345,
                "name": "Moderator",
                "added": ["manage_maps", "manage_users"],
            },
        }

        # Create
        create_response = await test_client.post("/api/v3/newsfeed/", json=payload)
        assert create_response.status_code == 201
        created_data = create_response.json()
        newsfeed_id = created_data["newsfeed_id"]

        # Retrieve
        get_response = await test_client.get(f"/api/v3/newsfeed/{newsfeed_id}")
        assert get_response.status_code == 200
        retrieved_data = get_response.json()

        # Validate round-trip
        assert retrieved_data["id"] == newsfeed_id
        assert retrieved_data["payload"]["type"] == "role"
        assert retrieved_data["payload"]["user_id"] == 12345
        assert retrieved_data["payload"]["name"] == "Moderator"
        assert retrieved_data["payload"]["added"] == ["manage_maps", "manage_users"]


class TestGetNewsfeedEvents:
    """GET /api/v3/newsfeed/"""

    async def test_happy_path(self, test_client):
        """List newsfeed events returns paginated list."""
        # Create a test event first
        payload = {
            "id": None,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": {
                "type": "announcement",
                "title": "Test Event",
                "content": "Test content",
            },
        }
        await test_client.post("/api/v3/newsfeed/", json=payload)

        response = await test_client.get("/api/v3/newsfeed/")

        assert response.status_code == 200
        data = response.json()
        # Can be list or None if no events
        if data is not None:
            assert isinstance(data, list)
            # If we have events, validate structure
            if len(data) > 0:
                event = data[0]
                assert "id" in event
                assert "timestamp" in event
                assert "payload" in event
                assert isinstance(event["id"], int)
                assert isinstance(event["timestamp"], str)
                assert isinstance(event["payload"], dict)

    async def test_requires_auth(self, unauthenticated_client):
        """List newsfeed events without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/newsfeed/")

        assert response.status_code == 401

    @pytest.mark.parametrize("page_size", [10, 20, 25, 50])
    async def test_pagination_page_size(self, test_client, page_size):
        """Pagination with different page sizes works correctly."""
        response = await test_client.get("/api/v3/newsfeed/", params={"page_size": page_size})

        assert response.status_code == 200
        data = response.json()
        # Can be None or list
        if data is not None:
            assert isinstance(data, list)
            # If we have results, they should not exceed page_size
            assert len(data) <= page_size

    @pytest.mark.parametrize("page_number", [1, 2, 3])
    async def test_pagination_page_number(self, test_client, page_number):
        """Pagination with different page numbers works correctly."""
        response = await test_client.get("/api/v3/newsfeed/", params={"page_number": page_number})

        assert response.status_code == 200
        data = response.json()
        # Can be None or list
        if data is not None:
            assert isinstance(data, list)

    @pytest.mark.parametrize(
        "event_type",
        [
            "new_map",
            "record",
            "archive",
            "unarchive",
            "bulk_archive",
            "bulk_unarchive",
            "guide",
            "legacy_record",
            "map_edit",
            "role",
            "announcement",
            "linked_map",
            "unlinked_map",
        ],
    )
    async def test_filter_by_event_type(self, test_client, event_type):
        """Filtering by event type returns only matching events."""
        response = await test_client.get("/api/v3/newsfeed/", params={"type": event_type})

        assert response.status_code == 200
        data = response.json()
        # Can be None or list
        if data is not None:
            assert isinstance(data, list)
            # All returned events should match the filter
            for event in data:
                assert event.get("event_type") == event_type or event["payload"]["type"] == event_type


class TestGetNewsfeedEvent:
    """GET /api/v3/newsfeed/{newsfeed_id}"""

    async def test_happy_path(self, test_client):
        """Get single newsfeed event returns event data."""
        # Create a test event first
        payload = {
            "id": None,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": {
                "type": "announcement",
                "title": "Specific Test Event",
                "content": "Specific content",
            },
        }
        create_response = await test_client.post("/api/v3/newsfeed/", json=payload)
        created_data = create_response.json()
        newsfeed_id = created_data["newsfeed_id"]

        response = await test_client.get(f"/api/v3/newsfeed/{newsfeed_id}")

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "timestamp" in data
        assert "payload" in data
        assert data["id"] == newsfeed_id
        assert isinstance(data["timestamp"], str)
        assert isinstance(data["payload"], dict)
        assert data["payload"]["type"] == "announcement"

    async def test_requires_auth(self, unauthenticated_client):
        """Get newsfeed event without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/newsfeed/999999999")

        assert response.status_code == 401

    async def test_not_found_returns_none(self, test_client):
        """Get non-existent newsfeed event returns None (200 with null body)."""
        response = await test_client.get("/api/v3/newsfeed/999999999")

        assert response.status_code == 200
        data = response.json()
        assert data is None
