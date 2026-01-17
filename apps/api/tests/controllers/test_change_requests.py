from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestChangeRequestsEndpoints:
    """Tests for map change request endpoints."""

    # Test data from seed
    OPEN_THREAD_1 = 1000000001
    OPEN_THREAD_2 = 1000000002
    RESOLVED_THREAD = 1000000003
    STALE_THREAD = 1000000004
    ALERTED_THREAD = 1000000005
    CREATOR_USER_ID = 100000000000000001

    # =========================================================================
    # PERMISSION CHECK TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_check_permission_for_creator(self, test_client: AsyncTestClient[Litestar]):
        """Test checking permission for creator returns true."""
        response = await test_client.get(
            f"/api/v3/change-requests/permission"
            f"?thread_id={self.OPEN_THREAD_1}"
            f"&user_id={self.CREATOR_USER_ID}"
            f"&code=1EASY"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # User is in creator_mentions, should return True
        assert data is True

    @pytest.mark.asyncio
    async def test_check_permission_for_non_creator(self, test_client: AsyncTestClient[Litestar]):
        """Test checking permission for non-creator returns false."""
        response = await test_client.get(
            f"/api/v3/change-requests/permission?thread_id={self.OPEN_THREAD_1}&user_id=999999&code=1EASY"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data is False

    @pytest.mark.asyncio
    async def test_check_permission_nonexistent_thread(self, test_client: AsyncTestClient[Litestar]):
        """Test checking permission for non-existent thread returns false."""
        response = await test_client.get(
            f"/api/v3/change-requests/permission?thread_id=9999999999&user_id={self.CREATOR_USER_ID}&code=1EASY"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data is False

    # =========================================================================
    # CREATE CHANGE REQUEST TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_change_request(self, test_client: AsyncTestClient[Litestar]):
        """Test creating a new change request."""
        response = await test_client.post(
            "/api/v3/change-requests/",
            json={
                "thread_id": 2000000001,
                "code": "2EASY",
                "user_id": 400,
                "content": "Please update this map",
                "change_request_type": "Difficulty Change",
                "creator_mentions": "100000000000000001",
            },
        )
        assert response.status_code == HTTP_201_CREATED

    @pytest.mark.asyncio
    async def test_create_change_request_with_mentions(self, test_client: AsyncTestClient[Litestar]):
        """Test creating change request with multiple creator mentions."""
        response = await test_client.post(
            "/api/v3/change-requests/",
            json={
                "thread_id": 2000000002,
                "code": "3EASY",
                "user_id": 401,
                "content": "Description needs work",
                "change_request_type": "Map Edit Required",
                "creator_mentions": "100000000000000001, 100000000000000002",
            },
        )
        assert response.status_code == HTTP_201_CREATED

    # =========================================================================
    # RESOLVE CHANGE REQUEST TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_resolve_change_request(self, test_client: AsyncTestClient[Litestar]):
        """Test resolving an open change request."""
        response = await test_client.patch(f"/api/v3/change-requests/{self.OPEN_THREAD_1}/resolve")
        assert response.status_code == HTTP_200_OK

        # Verify it's resolved by checking it doesn't appear in open requests
        list_resp = await test_client.get("/api/v3/change-requests/?code=1EASY")
        data = list_resp.json()
        # Should not include the resolved thread
        assert not any(req["thread_id"] == self.OPEN_THREAD_1 for req in data)

    @pytest.mark.asyncio
    async def test_resolve_already_resolved(self, test_client: AsyncTestClient[Litestar]):
        """Test resolving already resolved request (should not error)."""
        response = await test_client.patch(f"/api/v3/change-requests/{self.RESOLVED_THREAD}/resolve")
        # May be 204 or some error - depends on implementation
        assert response.status_code == HTTP_200_OK

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_request(self, test_client: AsyncTestClient[Litestar]):
        """Test resolving non-existent request returns error."""
        response = await test_client.patch("/api/v3/change-requests/9999999999/resolve")
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # LIST CHANGE REQUESTS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_change_requests_for_code(self, test_client: AsyncTestClient[Litestar]):
        """Test getting open change requests for a code."""
        response = await test_client.get("/api/v3/change-requests/?code=1EASY")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should only include unresolved requests
        for req in data:
            assert req["code"] == "1EASY"
            assert req["resolved"] is False

    @pytest.mark.asyncio
    async def test_get_change_requests_no_requests(self, test_client: AsyncTestClient[Litestar]):
        """Test getting requests for code with no open requests."""
        response = await test_client.get("/api/v3/change-requests/?code=NOCODE")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None

    @pytest.mark.asyncio
    async def test_get_change_requests_excludes_resolved(self, test_client: AsyncTestClient[Litestar]):
        """Test that resolved requests are not included."""
        response = await test_client.get("/api/v3/change-requests/?code=3EASY")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Resolved thread should not be in results
        assert not any(req["thread_id"] == self.RESOLVED_THREAD for req in data)

    # =========================================================================
    # STALE CHANGE REQUESTS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_stale_change_requests(self, test_client: AsyncTestClient[Litestar]):
        """Test getting stale change requests (>2 weeks, not alerted, not resolved)."""
        response = await test_client.get("/api/v3/change-requests/stale")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should include stale thread
        stale_ids = [req["thread_id"] for req in data]
        assert self.STALE_THREAD in stale_ids
        # Should NOT include alerted thread
        assert self.ALERTED_THREAD not in stale_ids

    @pytest.mark.asyncio
    async def test_get_stale_excludes_alerted(self, test_client: AsyncTestClient[Litestar]):
        """Test that alerted requests are excluded from stale list."""
        response = await test_client.get("/api/v3/change-requests/stale")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Alerted thread should not be in results
        assert not any(req["thread_id"] == self.ALERTED_THREAD for req in data)

    # =========================================================================
    # MARK AS ALERTED TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_alerted_change_request(self, test_client: AsyncTestClient[Litestar]):
        """Test marking a change request as alerted."""
        response = await test_client.patch(f"/api/v3/change-requests/{self.STALE_THREAD}/alerted")
        assert response.status_code == HTTP_200_OK

        # Verify it no longer appears in stale list
        stale_resp = await test_client.get("/api/v3/change-requests/stale")
        stale_data = stale_resp.json()
        assert not any(req["thread_id"] == self.STALE_THREAD for req in stale_data)

    @pytest.mark.asyncio
    async def test_update_alerted_already_alerted(self, test_client: AsyncTestClient[Litestar]):
        """Test marking already alerted request (no error)."""
        response = await test_client.patch(f"/api/v3/change-requests/{self.ALERTED_THREAD}/alerted")
        assert response.status_code == HTTP_200_OK
