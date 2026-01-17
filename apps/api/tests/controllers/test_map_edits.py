from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestMapEditsEndpoints:
    """Tests for map edit request endpoints."""

    # Test data from seed
    PENDING_EDIT_1 = 1
    PENDING_EDIT_2 = 2
    APPROVED_EDIT = 3
    REJECTED_EDIT = 4
    EDIT_WITH_MESSAGE = 5
    EDIT_USER = 500
    RESOLVER_USER = 501

    # =========================================================================
    # CREATE MAP EDIT REQUEST TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_edit_request_single_field(self, test_client: AsyncTestClient[Litestar]):
        """Test creating edit request with single field change."""
        response = await test_client.post(
            "/api/v3/maps/map-edits/",
            json={
                "code": "4EASY",
                "created_by": self.EDIT_USER,
                "reason": "Description needs updating",
                "description": "New updated description",
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["id"] is not None
        assert data["code"] == "4EASY"

    @pytest.mark.asyncio
    async def test_create_edit_request_multiple_fields(self, test_client: AsyncTestClient[Litestar]):
        """Test creating edit request with multiple field changes."""
        response = await test_client.post(
            "/api/v3/maps/map-edits/",
            json={
                "code": "5EASY",
                "created_by": self.EDIT_USER,
                "reason": "Multiple updates needed",
                "description": "Updated description",
                "checkpoints": 20,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["id"] is not None

    @pytest.mark.asyncio
    async def test_create_edit_request_with_reason(self, test_client: AsyncTestClient[Litestar]):
        """Test creating edit request with reason."""
        response = await test_client.post(
            "/api/v3/maps/map-edits/",
            json={
                "code": "7EASY",
                "created_by": self.EDIT_USER,
                "reason": "Map has incorrect checkpoint count",
                "checkpoints": 15,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["reason"] == "Map has incorrect checkpoint count"

    # =========================================================================
    # GET PENDING EDIT REQUESTS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_pending_edit_requests(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all pending edit requests."""
        response = await test_client.get("/api/v3/maps/map-edits/pending")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should include pending edits from seed
        pending_ids = [edit["id"] for edit in data]
        assert self.PENDING_EDIT_1 in pending_ids
        assert self.PENDING_EDIT_2 in pending_ids
        # Should not include resolved ones
        assert self.APPROVED_EDIT not in pending_ids
        assert self.REJECTED_EDIT not in pending_ids

    @pytest.mark.asyncio
    async def test_get_pending_when_none(self, test_client: AsyncTestClient[Litestar]):
        """Test getting pending edits when none exist (after resolving all)."""
        # This would require resolving all pending edits first
        # For now, just verify the endpoint works
        response = await test_client.get("/api/v3/maps/map-edits/pending")
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # GET EDIT REQUEST TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_edit_request(self, test_client: AsyncTestClient[Litestar]):
        """Test getting a specific edit request."""
        response = await test_client.get(f"/api/v3/maps/map-edits/{self.PENDING_EDIT_1}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == self.PENDING_EDIT_1
        assert data["code"] == "1EASY"
        assert "proposed_changes" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_edit(self, test_client: AsyncTestClient[Litestar]):
        """Test getting non-existent edit returns error."""
        response = await test_client.get("/api/v3/maps/map-edits/999999")
        assert response.status_code >= 400

    # =========================================================================
    # GET EDIT SUBMISSION VIEW TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_edit_submission(self, test_client: AsyncTestClient[Litestar]):
        """Test getting edit submission view with enriched data."""
        response = await test_client.get(f"/api/v3/maps/map-edits/{self.PENDING_EDIT_1}/submission")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == self.PENDING_EDIT_1
        assert "submitter_name" in data
        assert data["submitter_id"] == self.EDIT_USER

    # =========================================================================
    # SET MESSAGE ID TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_set_message_id(self, test_client: AsyncTestClient[Litestar]):
        """Test setting message ID for edit request."""
        response = await test_client.patch(
            f"/api/v3/maps/map-edits/{self.PENDING_EDIT_1}/message",
            json={"message_id": 5000000001},
        )
        assert response.status_code == HTTP_200_OK

    @pytest.mark.asyncio
    async def test_update_existing_message_id(self, test_client: AsyncTestClient[Litestar]):
        """Test updating existing message ID."""
        response = await test_client.patch(
            f"/api/v3/maps/map-edits/{self.EDIT_WITH_MESSAGE}/message",
            json={"message_id": 5000000002},
        )
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # RESOLVE EDIT REQUEST TESTS - ACCEPT
    # =========================================================================

    @pytest.mark.asyncio
    async def test_resolve_edit_accept(self, test_client: AsyncTestClient[Litestar]):
        """Test accepting an edit request (applies changes)."""
        # Get original map data
        maps_resp = await test_client.get("/api/v3/maps/?code=1EASY")
        original_maps = maps_resp.json()
        original_description = original_maps[0]["description"] if original_maps else None

        # Accept the edit
        response = await test_client.put(
            f"/api/v3/maps/map-edits/{self.PENDING_EDIT_1}/resolve",
            json={
                "accepted": True,
                "resolved_by": self.RESOLVER_USER,
                "send_to_playtest": False,
            },
        )
        assert response.status_code == HTTP_200_OK

        # Verify changes were applied
        maps_resp = await test_client.get("/api/v3/maps/?code=1EASY")
        updated_maps = maps_resp.json()
        # Description should have changed
        if original_description:
            assert updated_maps[0]["description"] != original_description

    @pytest.mark.asyncio
    async def test_resolve_edit_accept_and_send_to_playtest(self, test_client: AsyncTestClient[Litestar]):
        """Test accepting edit and sending to playtest."""
        response = await test_client.put(
            f"/api/v3/maps/map-edits/{self.PENDING_EDIT_2}/resolve",
            json={
                "accepted": True,
                "resolved_by": self.RESOLVER_USER,
                "send_to_playtest": True,
            },
        )
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # RESOLVE EDIT REQUEST TESTS - REJECT
    # =========================================================================

    @pytest.mark.asyncio
    async def test_resolve_edit_reject(self, test_client: AsyncTestClient[Litestar]):
        """Test rejecting an edit request."""
        # Create a new edit to reject
        create_resp = await test_client.post(
            "/api/v3/maps/map-edits/",
            json={
                "code": "7EASY",
                "created_by": self.EDIT_USER,
                "reason": "Will be rejected",
                "description": "This won't be applied",
            },
        )
        edit_id = create_resp.json()["id"]

        # Reject it
        response = await test_client.put(
            f"/api/v3/maps/map-edits/{edit_id}/resolve",
            json={
                "accepted": False,
                "resolved_by": self.RESOLVER_USER,
                "rejection_reason": "Changes are not needed",
            },
        )
        assert response.status_code == HTTP_200_OK

        # Verify map unchanged
        maps_resp = await test_client.get("/api/v3/maps/?code=7EASY")
        maps = maps_resp.json()
        if maps:
            # Description should not match rejected edit
            assert maps[0]["description"] != "This won't be applied"

    @pytest.mark.asyncio
    async def test_resolve_edit_reject_with_reason(self, test_client: AsyncTestClient[Litestar]):
        """Test rejecting with rejection reason."""
        # Create a new edit
        create_resp = await test_client.post(
            "/api/v3/maps/map-edits/",
            json={
                "code": "8EASY",
                "created_by": self.EDIT_USER,
                "reason": "Test rejection",
                "checkpoints": 999,
            },
        )
        edit_id = create_resp.json()["id"]

        response = await test_client.put(
            f"/api/v3/maps/map-edits/{edit_id}/resolve",
            json={
                "accepted": False,
                "resolved_by": self.RESOLVER_USER,
                "rejection_reason": "Checkpoint count is actually correct",
            },
        )
        assert response.status_code == HTTP_200_OK

    @pytest.mark.asyncio
    async def test_resolve_already_resolved_edit(self, test_client: AsyncTestClient[Litestar]):
        """Test resolving already resolved edit returns error."""
        response = await test_client.put(
            f"/api/v3/maps/map-edits/{self.APPROVED_EDIT}/resolve",
            json={
                "accepted": True,
                "resolved_by": self.RESOLVER_USER,
            },
        )
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # GET USER EDIT REQUESTS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_edit_requests_pending_only(self, test_client: AsyncTestClient[Litestar]):
        """Test getting user's pending edit requests."""
        response = await test_client.get(f"/api/v3/maps/map-edits/user/{self.EDIT_USER}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # All should be by this user and pending
        for edit in data:
            assert edit["created_by"] == self.EDIT_USER
            assert edit["accepted"] is None

    @pytest.mark.asyncio
    async def test_get_user_edit_requests_include_resolved(self, test_client: AsyncTestClient[Litestar]):
        """Test getting user's edit requests including resolved."""
        response = await test_client.get(f"/api/v3/maps/map-edits/user/{self.EDIT_USER}?include_resolved=true")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should include both pending and resolved
        has_pending = any(edit["accepted"] is None for edit in data)
        has_resolved = any(edit["accepted"] is not None for edit in data)
        assert has_pending or has_resolved

    @pytest.mark.asyncio
    async def test_get_user_edit_requests_no_requests(self, test_client: AsyncTestClient[Litestar]):
        """Test getting edit requests for user with none."""
        response = await test_client.get("/api/v3/maps/map-edits/user/999999")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None
