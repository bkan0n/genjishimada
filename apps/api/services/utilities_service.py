"""Service for utilities business logic."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os

import msgspec
from asyncpg import Pool
from genjishimada_sdk.logs import LogCreateRequest, MapClickCreateRequest
from litestar.datastructures import State

from repository.utilities_repository import UtilitiesRepository

from .base import BaseService


class LogClicksDebug(msgspec.Struct):
    """Debug structure for click logs."""

    id: int | None
    map_id: int | None
    user_id: int | None
    source: str | None
    user_agent: str | None
    ip_hash: str | None
    inserted_at: dt.datetime
    day_bucket: int


class UtilitiesService(BaseService):
    """Service for utilities business logic."""

    def __init__(self, pool: Pool, state: State, utilities_repo: UtilitiesRepository) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            utilities_repo: Utilities repository.
        """
        super().__init__(pool, state)
        self._utilities_repo = utilities_repo

    async def log_analytics(self, request: LogCreateRequest) -> None:
        """Log analytics command usage.

        Args:
            request: Analytics log request.
        """
        await self._utilities_repo.log_analytics(
            command_name=request.command_name,
            user_id=request.user_id,
            created_at=request.created_at,
            namespace=request.namespace,
        )

    async def log_map_click(self, request: MapClickCreateRequest) -> None:
        """Log map click with IP hashing.

        Args:
            request: Map click request.
        """
        secret = os.getenv("IP_HASH_SECRET", "").encode("utf-8")
        ip_hash = hmac.new(secret, request.ip_address.encode("utf-8"), hashlib.sha256).hexdigest()

        await self._utilities_repo.log_map_click(
            code=request.code,
            user_id=request.user_id,
            source=request.source,
            ip_hash=ip_hash,
        )

    async def fetch_map_clicks_debug(self, limit: int = 100) -> list[LogClicksDebug]:
        """Fetch recent map clicks for debugging.

        Args:
            limit: Maximum number of records.

        Returns:
            List of click logs.
        """
        rows = await self._utilities_repo.fetch_map_clicks_debug(limit)
        return msgspec.convert(rows, list[LogClicksDebug])


async def provide_utilities_service(
    state: State,
    utilities_repo: UtilitiesRepository,
) -> UtilitiesService:
    """Litestar DI provider for service.

    Args:
        state: Application state.
        utilities_repo: Utilities repository.

    Returns:
        UtilitiesService instance.
    """
    return UtilitiesService(state.db_pool, state, utilities_repo)
