"""Service for playtest business logic."""

from __future__ import annotations

from asyncpg import Pool
from litestar.datastructures import State

from repository.playtest_repository import PlaytestRepository

from .base import BaseService


class PlaytestService(BaseService):
    """Service for playtest business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        playtest_repo: PlaytestRepository,
    ) -> None:
        """Initialize service."""
        super().__init__(pool, state)
        self._playtest_repo = playtest_repo


async def provide_playtest_service(
    state: State,
    playtest_repo: PlaytestRepository,
) -> PlaytestService:
    """Litestar DI provider for service."""
    return PlaytestService(state.db_pool, state, playtest_repo)
