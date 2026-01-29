"""Tests for users repository."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import asyncpg
import pytest
from asyncpg import Pool
from pytest_databases.docker.postgres import PostgresService

from repository.exceptions import UniqueConstraintViolationError
from repository.users_repository import UsersRepository


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
    """Create users repository fixture.

    Args:
        db_pool: Database pool fixture.

    Returns:
        UsersRepository instance.
    """
    return UsersRepository(pool=db_pool)


@pytest.mark.asyncio
async def test_create_user(users_repo: UsersRepository) -> None:
    """Test creating a user."""
    user_id = 999999999999999
    nickname = "TestUser"
    global_name = "Test Global"

    # Create user
    await users_repo.create_user(user_id=user_id, nickname=nickname, global_name=global_name)

    # Verify user exists
    exists = await users_repo.check_user_exists(user_id)
    assert exists is True

    # Verify duplicate raises exception
    with pytest.raises(UniqueConstraintViolationError) as exc_info:
        await users_repo.create_user(user_id=user_id, nickname=nickname, global_name=global_name)
    assert exc_info.value.constraint_name == "users_pkey"


@pytest.mark.asyncio
async def test_fetch_user(users_repo: UsersRepository) -> None:
    """Test fetching a user."""
    user_id = 999999999999998
    nickname = "FetchTest"
    global_name = "Fetch Global"

    # Create user
    await users_repo.create_user(user_id=user_id, nickname=nickname, global_name=global_name)

    # Fetch user
    user = await users_repo.fetch_user(user_id)
    assert user is not None
    assert user["id"] == user_id
    assert user["nickname"] == nickname
    assert user["global_name"] == global_name
    assert user["coins"] == 0


@pytest.mark.asyncio
async def test_overwatch_usernames(users_repo: UsersRepository) -> None:
    """Test Overwatch usernames operations."""
    user_id = 999999999999997
    await users_repo.create_user(user_id=user_id, nickname="OwTest", global_name="OW Global")

    # Insert usernames
    await users_repo.insert_overwatch_username(user_id, "PrimaryName", is_primary=True)
    await users_repo.insert_overwatch_username(user_id, "SecondaryName", is_primary=False)

    # Fetch usernames
    usernames = await users_repo.fetch_overwatch_usernames(user_id)
    assert len(usernames) == 2
    assert usernames[0]["username"] == "PrimaryName"
    assert usernames[0]["is_primary"] is True
    assert usernames[1]["username"] == "SecondaryName"
    assert usernames[1]["is_primary"] is False

    # Delete usernames
    await users_repo.delete_overwatch_usernames(user_id)
    usernames = await users_repo.fetch_overwatch_usernames(user_id)
    assert len(usernames) == 0


@pytest.mark.asyncio
async def test_notifications(users_repo: UsersRepository) -> None:
    """Test notification settings operations."""
    user_id = 999999999999996
    await users_repo.create_user(user_id=user_id, nickname="NotifTest", global_name="Notif Global")

    # Initially no flags
    flags = await users_repo.fetch_user_notifications(user_id)
    assert flags is None

    # Upsert flags
    await users_repo.upsert_user_notifications(user_id, 7)
    flags = await users_repo.fetch_user_notifications(user_id)
    assert flags == 7

    # Update flags
    await users_repo.upsert_user_notifications(user_id, 15)
    flags = await users_repo.fetch_user_notifications(user_id)
    assert flags == 15


@pytest.mark.asyncio
async def test_fake_member(users_repo: UsersRepository) -> None:
    """Test fake member creation and linking."""
    # Create fake member
    fake_id = await users_repo.create_fake_member("FakeMember")
    assert fake_id < 100000000

    # Verify exists
    exists = await users_repo.check_user_exists(fake_id)
    assert exists is True

    # Create real user
    real_id = 999999999999995
    await users_repo.create_user(user_id=real_id, nickname="RealUser", global_name="Real Global")

    # Delete fake user (without linking for this test)
    await users_repo.delete_user(fake_id)
    exists = await users_repo.check_user_exists(fake_id)
    assert exists is False
