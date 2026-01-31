"""Shared fixtures for service unit tests.

This module provides mock fixtures for repositories, pools, and state objects
used across service unit tests. All fixtures use AsyncMock to handle async/await
automatically.
"""

import pytest
from asyncpg import Pool
from litestar.datastructures import State

from repository.auth_repository import AuthRepository
from repository.autocomplete_repository import AutocompleteRepository
from repository.change_requests_repository import ChangeRequestsRepository
from repository.community_repository import CommunityRepository
from repository.completions_repository import CompletionsRepository
from repository.jobs_repository import InternalJobsRepository
from repository.lootbox_repository import LootboxRepository
from repository.maps_repository import MapsRepository
from repository.newsfeed_repository import NewsfeedRepository
from repository.notifications_repository import NotificationsRepository
from repository.playtest_repository import PlaytestRepository
from repository.rank_card_repository import RankCardRepository
from repository.users_repository import UsersRepository
from repository.utilities_repository import UtilitiesRepository
from services.image_storage_service import ImageStorageService
from services.notifications_service import NotificationsService


@pytest.fixture
def mock_pool(mocker):
    """Mock AsyncPG connection pool.

    Returns:
        AsyncMock pool with acquire() context manager configured.
    """
    pool = mocker.MagicMock(spec=Pool)
    conn = mocker.MagicMock()

    # Mock the context manager for pool.acquire()
    async def mock_acquire_aenter(self):
        return conn

    async def mock_acquire_aexit(self, exc_type, exc_val, exc_tb):
        return None

    acquire_cm = mocker.MagicMock()
    acquire_cm.__aenter__ = mock_acquire_aenter
    acquire_cm.__aexit__ = mock_acquire_aexit
    pool.acquire.return_value = acquire_cm

    # Mock the context manager for conn.transaction()
    async def mock_transaction_aenter(self):
        return None

    async def mock_transaction_aexit(self, exc_type, exc_val, exc_tb):
        return None

    transaction_cm = mocker.MagicMock()
    transaction_cm.__aenter__ = mock_transaction_aenter
    transaction_cm.__aexit__ = mock_transaction_aexit
    conn.transaction.return_value = transaction_cm

    return pool


@pytest.fixture
def mock_state(mocker):
    """Mock Litestar State.

    Returns:
        Mock State with mq_channel_pool configured for BaseService.publish_message.
    """
    state = mocker.Mock(spec=State)
    state.mq_channel_pool = mocker.AsyncMock()
    return state


# Repository Fixtures


@pytest.fixture
def mock_auth_repo(mocker):
    """Mock AuthRepository."""
    return mocker.AsyncMock(spec=AuthRepository)


@pytest.fixture
def mock_autocomplete_repo(mocker):
    """Mock AutocompleteRepository."""
    return mocker.AsyncMock(spec=AutocompleteRepository)


@pytest.fixture
def mock_change_requests_repo(mocker):
    """Mock ChangeRequestsRepository."""
    return mocker.AsyncMock(spec=ChangeRequestsRepository)


@pytest.fixture
def mock_community_repo(mocker):
    """Mock CommunityRepository."""
    return mocker.AsyncMock(spec=CommunityRepository)


@pytest.fixture
def mock_completions_repo(mocker):
    """Mock CompletionsRepository."""
    return mocker.AsyncMock(spec=CompletionsRepository)


@pytest.fixture
def mock_jobs_repo(mocker):
    """Mock InternalJobsRepository."""
    return mocker.AsyncMock(spec=InternalJobsRepository)


@pytest.fixture
def mock_lootbox_repo(mocker):
    """Mock LootboxRepository."""
    return mocker.AsyncMock(spec=LootboxRepository)


@pytest.fixture
def mock_maps_repo(mocker):
    """Mock MapsRepository."""
    return mocker.AsyncMock(spec=MapsRepository)


@pytest.fixture
def mock_newsfeed_repo(mocker):
    """Mock NewsfeedRepository."""
    return mocker.AsyncMock(spec=NewsfeedRepository)


@pytest.fixture
def mock_notifications_repo(mocker):
    """Mock NotificationsRepository."""
    return mocker.AsyncMock(spec=NotificationsRepository)


@pytest.fixture
def mock_playtest_repo(mocker):
    """Mock PlaytestRepository."""
    return mocker.AsyncMock(spec=PlaytestRepository)


@pytest.fixture
def mock_rank_card_repo(mocker):
    """Mock RankCardRepository."""
    return mocker.AsyncMock(spec=RankCardRepository)


@pytest.fixture
def mock_users_repo(mocker):
    """Mock UsersRepository."""
    return mocker.AsyncMock(spec=UsersRepository)


@pytest.fixture
def mock_utilities_repo(mocker):
    """Mock UtilitiesRepository."""
    return mocker.AsyncMock(spec=UtilitiesRepository)


# Service Fixtures (for services that depend on other services)


@pytest.fixture
def mock_image_storage_service(mocker):
    """Mock ImageStorageService."""
    return mocker.AsyncMock(spec=ImageStorageService)


@pytest.fixture
def mock_notifications_service(mocker):
    """Mock NotificationsService."""
    return mocker.AsyncMock(spec=NotificationsService)
