"""Base repository class."""

from __future__ import annotations

from asyncpg import Connection, Pool


class BaseRepository:
    """Base class for all repositories.

    Repositories handle data access and raise repository-specific exceptions.
    They accept an optional connection parameter for transaction participation.
    """

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        self._pool = pool

    def _get_connection(self, conn: Connection | None = None) -> Connection | Pool:
        """Get connection for query execution.

        Args:
            conn: Optional connection from transaction context.

        Returns:
            Connection if provided (for transactions), otherwise pool.
        """
        return conn or self._pool
