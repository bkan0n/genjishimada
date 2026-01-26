"""Repository for completions domain database operations."""

from __future__ import annotations

from asyncpg import Pool

from repository.base import BaseRepository


class CompletionsRepository(BaseRepository):
    """Repository for completions domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    # Query methods will be added in subsequent tasks.
