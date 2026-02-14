"""Change requests service for business logic."""

from __future__ import annotations

import msgspec
from asyncpg import Pool
from genjishimada_sdk.change_requests import (
    ChangeRequestCreateRequest,
    ChangeRequestResponse,
    StaleChangeRequestResponse,
)
from litestar.datastructures import State

from repository.change_requests_repository import ChangeRequestsRepository
from repository.exceptions import ForeignKeyViolationError, UniqueConstraintViolationError
from repository.maps_repository import MapsRepository

from .base import BaseService
from .exceptions.change_requests import ChangeRequestAlreadyExistsError, MapNotFoundError


class ChangeRequestsService(BaseService):
    """Service for change requests business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        change_requests_repo: ChangeRequestsRepository,
        maps_repo: MapsRepository,
    ) -> None:
        """Initialize change requests service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            change_requests_repo: Change requests repository.
            maps_repo: Maps repository for map validation.
        """
        super().__init__(pool, state)
        self._change_requests_repo = change_requests_repo
        self._maps_repo = maps_repo

    async def check_permission(self, thread_id: int, user_id: int, code: str) -> bool:
        """Check if user has creator permission for a change request.

        Args:
            thread_id: Discord thread ID.
            user_id: User ID to check.
            code: Overwatch map code.

        Returns:
            True if user is in creator_mentions, False otherwise.
        """
        creator_mentions = await self._change_requests_repo.fetch_creator_mentions(thread_id, code)
        if not creator_mentions:
            return False
        return str(user_id) in creator_mentions

    async def create_request(self, data: ChangeRequestCreateRequest) -> None:
        """Create a new change request.

        Args:
            data: Change request creation data.

        Raises:
            MapNotFoundError: If map doesn't exist.
            ChangeRequestAlreadyExistsError: If change request already exists for this thread.
        """
        map_exists = await self._maps_repo.check_code_exists(data.code)
        if not map_exists:
            raise MapNotFoundError(data.code)

        try:
            await self._change_requests_repo.create_request(
                thread_id=data.thread_id,
                code=data.code,
                user_id=data.user_id,
                content=data.content,
                change_request_type=data.change_request_type,
                creator_mentions=data.creator_mentions,
            )
        except UniqueConstraintViolationError as e:
            if "thread_id" in e.constraint_name or "pkey" in e.constraint_name:
                raise ChangeRequestAlreadyExistsError(data.thread_id) from e
            raise
        except ForeignKeyViolationError as e:
            if "code" in e.constraint_name:
                raise MapNotFoundError(data.code) from e
            raise

    async def resolve_request(self, thread_id: int) -> None:
        """Mark a change request as resolved.

        Args:
            thread_id: Discord thread ID.
        """
        await self._change_requests_repo.mark_resolved(thread_id)

    async def get_unresolved_requests(self, code: str) -> list[ChangeRequestResponse]:
        """Get unresolved change requests for a map.

        Args:
            code: Overwatch map code.

        Returns:
            List of unresolved change requests.
        """
        rows = await self._change_requests_repo.fetch_unresolved_requests(code)
        return msgspec.convert(rows, list[ChangeRequestResponse])

    async def get_stale_requests(self) -> list[StaleChangeRequestResponse]:
        """Get stale change requests needing follow-up.

        Returns:
            List of stale change requests.
        """
        rows = await self._change_requests_repo.fetch_stale_requests()
        return msgspec.convert(rows, list[StaleChangeRequestResponse])

    async def mark_alerted(self, thread_id: int) -> None:
        """Mark a change request as alerted.

        Args:
            thread_id: Discord thread ID.
        """
        await self._change_requests_repo.mark_alerted(thread_id)


async def provide_change_requests_service(
    state: State,
    change_requests_repo: ChangeRequestsRepository,
    maps_repo: MapsRepository,
) -> ChangeRequestsService:
    """Litestar DI provider for ChangeRequestsService.

    Args:
        state: Application state.
        change_requests_repo: Change requests repository instance.
        maps_repo: Maps repository instance.

    Returns:
        ChangeRequestsService instance.
    """
    return ChangeRequestsService(state.db_pool, state, change_requests_repo, maps_repo)
