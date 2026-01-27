"""Tests for users service."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import asyncpg
import pytest
from asyncpg import Pool
from genjishimada_sdk.users import UserCreateRequest, UserUpdateRequest
from msgspec import UNSET
from pytest_databases.docker.postgres import PostgresService

from repository.users_repository import UsersRepository
from services.users_service import UsersService
from utilities.errors import CustomHTTPException


@pytest.fixture
async def db_pool(postgres_service: PostgresService) -> AsyncGenerator[asyncpg.Pool]:
    """Create asyncpg pool for tests."""
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    yield pool
    await pool.close()


@pytest.fixture
def users_repo(db_pool: Pool) -> UsersRepository:
    """Create users repository fixture."""
    return UsersRepository(pool=db_pool)


@pytest.fixture
def users_service(users_repo: UsersRepository) -> UsersService:
    """Create users service fixture."""
    return UsersService(users_repo=users_repo)


@pytest.mark.asyncio
async def test_create_user(users_service: UsersService) -> None:
    """Test creating a user via service."""
    data = UserCreateRequest(
        id=999999999999994,
        nickname="ServiceTest",
        global_name="Service Global",
    )

    user = await users_service.create_user(data)
    assert user.id == data.id
    assert user.nickname == data.nickname
    assert user.global_name == data.global_name
    assert user.coins == 0
    assert user.overwatch_usernames == []

    # Test duplicate raises CustomHTTPException
    with pytest.raises(CustomHTTPException) as exc_info:
        await users_service.create_user(data)
    assert "already exists" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_create_user_fake_id_rejected(users_service: UsersService) -> None:
    """Test that IDs below 100000000 are rejected."""
    data = UserCreateRequest(
        id=50000000,
        nickname="FakeID",
        global_name="Fake Global",
    )

    with pytest.raises(CustomHTTPException) as exc_info:
        await users_service.create_user(data)
    assert "fake member endpoint" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_user(users_service: UsersService) -> None:
    """Test getting a user via service."""
    # Create user
    data = UserCreateRequest(
        id=999999999999993,
        nickname="GetTest",
        global_name="Get Global",
    )
    await users_service.create_user(data)

    # Get user
    user = await users_service.get_user(data.id)
    assert user is not None
    assert user.id == data.id
    assert user.nickname == data.nickname
    assert user.global_name == data.global_name

    # Get non-existent user
    user = await users_service.get_user(888888888888888)
    assert user is None


@pytest.mark.asyncio
async def test_update_user_names(users_service: UsersService) -> None:
    """Test updating user names via service."""
    # Create user
    data = UserCreateRequest(
        id=999999999999992,
        nickname="UpdateTest",
        global_name="Update Global",
    )
    await users_service.create_user(data)

    # Update nickname only
    update_data = UserUpdateRequest(nickname="NewNickname", global_name=UNSET)
    await users_service.update_user_names(data.id, update_data)

    # Verify update
    user = await users_service.get_user(data.id)
    assert user is not None
    assert user.nickname == "NewNickname"
    assert user.global_name == "Update Global"  # Unchanged


@pytest.mark.asyncio
async def test_overwatch_usernames_service(users_service: UsersService) -> None:
    """Test Overwatch usernames via service."""
    from genjishimada_sdk.users import OverwatchUsernameItem

    # Create user
    data = UserCreateRequest(
        id=999999999999991,
        nickname="OwServiceTest",
        global_name="OW Service Global",
    )
    await users_service.create_user(data)

    # Set usernames
    usernames = [
        OverwatchUsernameItem(username="Primary", is_primary=True),
        OverwatchUsernameItem(username="Secondary", is_primary=False),
    ]
    await users_service.set_overwatch_usernames(data.id, usernames)

    # Get response
    response = await users_service.get_overwatch_usernames_response(data.id)
    assert response.user_id == data.id
    assert response.primary == "Primary"
    assert response.secondary == "Secondary"
    assert response.tertiary is None
