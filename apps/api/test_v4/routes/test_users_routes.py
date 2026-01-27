"""Tests for users routes."""

from __future__ import annotations

import pytest
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from litestar.testing import AsyncTestClient


@pytest.mark.asyncio
async def test_create_user_route(test_client: AsyncTestClient) -> None:
    """Test POST /api/v4/users endpoint."""
    payload = {
        "id": 999999999999990,
        "nickname": "RouteTest",
        "global_name": "Route Global",
    }

    response = await test_client.post("/api/v4/users", json=payload)
    assert response.status_code == HTTP_201_CREATED
    data = response.json()
    assert data["id"] == payload["id"]
    assert data["nickname"] == payload["nickname"]
    assert data["global_name"] == payload["global_name"]


@pytest.mark.asyncio
async def test_get_user_route(test_client: AsyncTestClient) -> None:
    """Test GET /api/v4/users/{user_id} endpoint."""
    # Create user first
    payload = {
        "id": 999999999999989,
        "nickname": "GetRouteTest",
        "global_name": "Get Route Global",
    }
    await test_client.post("/api/v4/users", json=payload)

    # Get user
    response = await test_client.get(f"/api/v4/users/{payload['id']}")
    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data["id"] == payload["id"]
    assert data["nickname"] == payload["nickname"]


@pytest.mark.asyncio
async def test_check_user_exists_route(test_client: AsyncTestClient) -> None:
    """Test GET /api/v4/users/{user_id}/exists endpoint."""
    # Create user
    payload = {
        "id": 999999999999988,
        "nickname": "ExistsTest",
        "global_name": "Exists Global",
    }
    await test_client.post("/api/v4/users", json=payload)

    # Check exists (true)
    response = await test_client.get(f"/api/v4/users/{payload['id']}/exists")
    assert response.status_code == HTTP_200_OK
    assert response.json() is True

    # Check non-existent (false)
    response = await test_client.get("/api/v4/users/888888888888888/exists")
    assert response.status_code == HTTP_200_OK
    assert response.json() is False


@pytest.mark.asyncio
async def test_update_user_names_route(test_client: AsyncTestClient) -> None:
    """Test PATCH /api/v4/users/{user_id} endpoint."""
    # Create user
    payload = {
        "id": 999999999999987,
        "nickname": "PatchTest",
        "global_name": "Patch Global",
    }
    await test_client.post("/api/v4/users", json=payload)

    # Update nickname
    update_payload = {"nickname": "NewPatchNickname"}
    response = await test_client.patch(f"/api/v4/users/{payload['id']}", json=update_payload)
    assert response.status_code == HTTP_200_OK

    # Verify update
    response = await test_client.get(f"/api/v4/users/{payload['id']}")
    data = response.json()
    assert data["nickname"] == "NewPatchNickname"


@pytest.mark.asyncio
async def test_update_user_names_empty_fails(test_client: AsyncTestClient) -> None:
    """Test PATCH /api/v4/users/{user_id} with empty payload fails."""
    response = await test_client.patch("/api/v4/users/999999999999986", json={})
    assert response.status_code == HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_overwatch_usernames_routes(test_client: AsyncTestClient) -> None:
    """Test Overwatch usernames PUT and GET endpoints."""
    # Create user
    payload = {
        "id": 999999999999985,
        "nickname": "OwRouteTest",
        "global_name": "OW Route Global",
    }
    await test_client.post("/api/v4/users", json=payload)

    # Set usernames
    usernames_payload = {
        "usernames": [
            {"username": "PrimaryRoute", "is_primary": True},
            {"username": "SecondaryRoute", "is_primary": False},
        ]
    }
    response = await test_client.put(f"/api/v4/users/{payload['id']}/overwatch", json=usernames_payload)
    assert response.status_code == HTTP_200_OK
    assert response.json()["success"] is True

    # Get usernames
    response = await test_client.get(f"/api/v4/users/{payload['id']}/overwatch")
    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data["user_id"] == payload["id"]
    assert data["primary"] == "PrimaryRoute"
    assert data["secondary"] == "SecondaryRoute"


@pytest.mark.asyncio
async def test_create_fake_member_route(test_client: AsyncTestClient) -> None:
    """Test POST /api/v4/users/fake endpoint."""
    response = await test_client.post("/api/v4/users/fake", params={"name": "FakeRouteTest"})
    assert response.status_code == HTTP_201_CREATED
    fake_id = response.json()
    assert isinstance(fake_id, int)
    assert fake_id < 100000000


@pytest.mark.asyncio
async def test_list_users_route(test_client: AsyncTestClient) -> None:
    """Test GET /api/v4/users endpoint."""
    response = await test_client.get("/api/v4/users")
    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
