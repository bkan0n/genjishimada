"""Repository for playtest data access."""

from __future__ import annotations

from asyncpg import Pool
from litestar.datastructures import State

from .base import BaseRepository


class PlaytestRepository(BaseRepository):
    """Repository for playtest data access."""

    # Placeholder - will be implemented in Task 1
    pass


async def provide_playtest_repository(state: State) -> PlaytestRepository:
    """Litestar DI provider for repository.

    Args:
        state: Application state.

    Returns:
        Repository instance.
    """
    return PlaytestRepository(state.db_pool)
