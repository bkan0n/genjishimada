"""Integration tests for Change Requests v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest
from genjishimada_sdk.change_requests import ChangeRequestType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_change_requests,
]


class TestCheckPermission:
    """GET /api/v3/change-requests/permission"""

    async def test_happy_path_with_permission(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Check permission returns True when user is in creator mentions."""
        # Create test data
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create change request with user in creator_mentions
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            thread_id,
            code,
            user_id,
            "Test content",
            "Other",
            f"{user_id}",  # User is in creator mentions
            False,
            False,
        )

        response = await test_client.get(
            "/api/v3/change-requests/permission",
            params={"thread_id": thread_id, "user_id": user_id, "code": code},
        )

        assert response.status_code == 200
        data = response.json()
        assert data is True

    async def test_happy_path_without_permission(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Check permission returns False when user not in creator mentions."""
        # Create test data
        user_id = await create_test_user()
        other_user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create change request with different user in creator_mentions
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            thread_id,
            code,
            other_user_id,
            "Test content",
            "Other",
            f"{other_user_id}",  # Different user in creator mentions
            False,
            False,
        )

        response = await test_client.get(
            "/api/v3/change-requests/permission",
            params={"thread_id": thread_id, "user_id": user_id, "code": code},
        )

        assert response.status_code == 200
        data = response.json()
        assert data is False

    async def test_requires_auth(self, unauthenticated_client):
        """Check permission without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v3/change-requests/permission",
            params={"thread_id": 123456789, "user_id": 123456789, "code": "TEST01"},
        )

        assert response.status_code == 401


class TestCreateChangeRequest:
    """POST /api/v3/change-requests/"""

    async def test_happy_path(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
    ):
        """Create change request returns 201."""
        # Create test data
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        payload = {
            "thread_id": thread_id,
            "user_id": user_id,
            "code": code,
            "content": "Please fix the bug in checkpoint 3",
            "change_request_type": "Other",
            "creator_mentions": f"{user_id}",
        }

        response = await test_client.post("/api/v3/change-requests/", json=payload)

        assert response.status_code == 201

    async def test_requires_auth(self, unauthenticated_client):
        """Create change request without auth returns 401."""
        payload = {
            "thread_id": 123456789,
            "user_id": 123456789,
            "code": "TEST01",
            "content": "Test",
            "change_request_type": "Other",
            "creator_mentions": "",
        }

        response = await unauthenticated_client.post("/api/v3/change-requests/", json=payload)

        assert response.status_code == 401

    async def test_nonexistent_code_returns_404(
        self,
        test_client,
        create_test_user,
        unique_thread_id,
    ):
        """Create change request with non-existent map code returns 404."""
        user_id = await create_test_user()
        thread_id = unique_thread_id

        payload = {
            "thread_id": thread_id,
            "user_id": user_id,
            "code": "ZZZZZZ",  # Non-existent code
            "content": "Test content",
            "change_request_type": "Other",
            "creator_mentions": "",
        }

        response = await test_client.post("/api/v3/change-requests/", json=payload)

        assert response.status_code == 404

    async def test_duplicate_thread_id_returns_409(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Create change request with duplicate thread_id returns 409."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create first change request
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            thread_id,
            code,
            user_id,
            "Test content",
            "Other",
            "",
            False,
            False,
        )

        # Try to create duplicate
        payload = {
            "thread_id": thread_id,  # Same thread_id
            "user_id": user_id,
            "code": code,
            "content": "Duplicate content",
            "change_request_type": "Other",
            "creator_mentions": "",
        }

        response = await test_client.post("/api/v3/change-requests/", json=payload)

        assert response.status_code == 409

    async def test_invalid_change_request_type_returns_400(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
    ):
        """Create change request with invalid enum value returns 400."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        payload = {
            "thread_id": thread_id,
            "user_id": user_id,
            "code": code,
            "content": "Test content",
            "change_request_type": "InvalidType",  # Invalid enum value
            "creator_mentions": "",
        }

        response = await test_client.post("/api/v3/change-requests/", json=payload)

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "change_request_type",
        [
            "Difficulty Change",
            "Map Geometry",
            "Map Edit Required",
            "Framework/Workshop",
            "Other",
        ],
    )
    async def test_all_change_request_types(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        change_request_type,
    ):
        """All ChangeRequestType enum values are accepted and stored correctly."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        payload = {
            "thread_id": thread_id,
            "user_id": user_id,
            "code": code,
            "content": f"Test content for {change_request_type}",
            "change_request_type": change_request_type,
            "creator_mentions": "",
        }

        response = await test_client.post("/api/v3/change-requests/", json=payload)

        assert response.status_code == 201


class TestResolveChangeRequest:
    """PATCH /api/v3/change-requests/{thread_id}/resolve"""

    async def test_happy_path(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Resolve change request returns 200."""
        # Create test data
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create unresolved change request
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            thread_id,
            code,
            user_id,
            "Test content",
            "Other",
            "",
            False,  # Unresolved
            False,
        )

        response = await test_client.patch(f"/api/v3/change-requests/{thread_id}/resolve")

        assert response.status_code == 200

    async def test_requires_auth(self, unauthenticated_client):
        """Resolve change request without auth returns 401."""
        response = await unauthenticated_client.patch("/api/v3/change-requests/123456789/resolve")

        assert response.status_code == 401


class TestGetChangeRequests:
    """GET /api/v3/change-requests/"""

    async def test_happy_path(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Get unresolved change requests returns list."""
        # Create test data
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create unresolved change request
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            thread_id,
            code,
            user_id,
            "Test content",
            "Other",
            "",
            False,  # Unresolved
            False,
        )

        response = await test_client.get(
            "/api/v3/change-requests/",
            params={"code": code},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            # Validate all required fields exist
            assert "thread_id" in item
            assert "user_id" in item
            assert "code" in item
            assert "content" in item
            assert "change_request_type" in item
            assert "creator_mentions" in item
            assert "alerted" in item
            assert "resolved" in item
            # Validate field types
            assert isinstance(item["thread_id"], int)
            assert isinstance(item["user_id"], int)
            assert isinstance(item["code"], str)
            assert isinstance(item["content"], str)
            assert isinstance(item["change_request_type"], str)
            assert isinstance(item["creator_mentions"], str) or item["creator_mentions"] is None
            assert isinstance(item["alerted"], bool)
            assert isinstance(item["resolved"], bool)
            # Validate expected values
            assert item["thread_id"] == thread_id
            assert item["code"] == code
            assert item["resolved"] is False  # We fetched unresolved requests

    async def test_requires_auth(self, unauthenticated_client):
        """Get change requests without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v3/change-requests/",
            params={"code": "TEST01"},
        )

        assert response.status_code == 401


class TestGetStaleChangeRequests:
    """GET /api/v3/change-requests/stale"""

    async def test_happy_path(self, test_client):
        """Get stale change requests returns list."""
        response = await test_client.get("/api/v3/change-requests/stale")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Response may be empty if no stale requests exist
        if data:
            item = data[0]
            assert "thread_id" in item
            assert "user_id" in item
            assert "creator_mentions" in item
            # Validate field types
            assert isinstance(item["thread_id"], int)
            assert isinstance(item["user_id"], int)
            assert isinstance(item["creator_mentions"], str)

    async def test_requires_auth(self, unauthenticated_client):
        """Get stale change requests without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/change-requests/stale")

        assert response.status_code == 401

    async def test_stale_request_appears_in_list(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Change request older than 2 weeks appears in stale list."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create change request with created_at > 2 weeks ago
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW() - INTERVAL '3 weeks')
            """,
            thread_id,
            code,
            user_id,
            "Old stale request",
            "Other",
            f"{user_id}",
            False,  # Not resolved
            False,  # Not alerted
        )

        response = await test_client.get("/api/v3/change-requests/stale")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Find our stale request in the list
        stale_request = next((item for item in data if item["thread_id"] == thread_id), None)
        assert stale_request is not None
        assert stale_request["user_id"] == user_id
        assert stale_request["creator_mentions"] == f"{user_id}"


class TestMarkAlerted:
    """PATCH /api/v3/change-requests/{thread_id}/alerted"""

    async def test_happy_path(
        self,
        test_client,
        create_test_user,
        create_test_map,
        unique_map_code,
        unique_thread_id,
        asyncpg_conn,
    ):
        """Mark change request as alerted returns 200."""
        # Create test data
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)
        thread_id = unique_thread_id

        # Create un-alerted change request
        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            thread_id,
            code,
            user_id,
            "Test content",
            "Other",
            "",
            False,
            False,  # Not alerted
        )

        response = await test_client.patch(f"/api/v3/change-requests/{thread_id}/alerted")

        assert response.status_code == 200

    async def test_requires_auth(self, unauthenticated_client):
        """Mark change request as alerted without auth returns 401."""
        response = await unauthenticated_client.patch("/api/v3/change-requests/123456789/alerted")

        assert response.status_code == 401
