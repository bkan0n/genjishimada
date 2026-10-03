"""Regression tests for sharing the application transaction across services."""

from unittest.mock import MagicMock, AsyncMock
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    conn.transaction.return_value.__aenter__ = AsyncMock()
    return pool


@pytest.mark.asyncio
async def test_Q01_nested_services_share_transaction_connection(mock_pool):
    from utilities import transactions

    async with transactions.transaction(mock_pool) as conn:
        async with transactions.transaction(mock_pool) as nested:
            assert nested is conn
        assert transactions.current_connection.get() is conn
    assert transactions.current_connection.get() is None
    mock_pool.acquire.assert_called_once()


@pytest.mark.asyncio
async def test_Q01_repository_uses_current_transaction(mock_pool):
    from repository.base import BaseRepository
    from utilities import transactions

    repo = BaseRepository(mock_pool)
    async with transactions.transaction(mock_pool) as conn:
        assert repo._get_connection() is conn


@pytest.mark.asyncio
async def test_Q01_background_task_does_not_inherit_connection(mock_pool):
    import asyncio
    from utilities.transactions import transaction, active_connection

    async def child():
        return active_connection()

    async with transaction(mock_pool):
        assert await asyncio.create_task(child()) is None


@pytest.mark.asyncio
async def test_Q01_after_commit_not_called_on_rollback(mock_pool):
    from utilities.transactions import transaction, on_commit

    callbacks = []
    with pytest.raises(ValueError):
        async with transaction(mock_pool):
            on_commit(lambda: callbacks.append("committed"))
            raise ValueError("rollback")
    assert callbacks == []
