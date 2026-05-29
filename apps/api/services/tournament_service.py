"""Service for tournament domain business logic."""

from __future__ import annotations

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    TournamentCategoryPatchRequest,
    TournamentCategoryResponse,
    TournamentConfigPatchRequest,
    TournamentConfigResponse,
)
from litestar.datastructures import State

from repository.exceptions import UniqueConstraintViolationError
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.exceptions.tournaments import (
    CategoryLockedError,
    CategoryNameExistsError,
    CategoryNotFoundError,
)


class TournamentService(BaseService):
    """Service for tournament config and category business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        tournament_repo: TournamentRepository,
    ) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            tournament_repo: Tournament repository instance.
        """
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo

    async def get_config(self) -> TournamentConfigResponse:
        """Get tournament configuration.

        Returns:
            Tournament configuration.
        """
        config = await self._tournament_repo.fetch_config()
        return msgspec.convert(config, TournamentConfigResponse)

    async def update_config(self, data: TournamentConfigPatchRequest) -> TournamentConfigResponse:
        """Update tournament configuration.

        Only updates fields that are not UNSET.

        Args:
            data: Partial config update request.

        Returns:
            Updated tournament configuration.
        """
        updates: dict[str, object] = {}
        if data.blacklist_weeks is not msgspec.UNSET:
            updates["blacklist_weeks"] = data.blacklist_weeks
        if updates:
            await self._tournament_repo.update_config(updates)
        return await self.get_config()

    async def create_category(self, data: TournamentCategoryCreateRequest) -> TournamentCategoryResponse:
        """Create a tournament category.

        No active cycle check is required for category creation.

        Args:
            data: Category creation request.

        Returns:
            Created tournament category.

        Raises:
            CategoryNameExistsError: If a category with this name already exists.
        """
        try:
            row = await self._tournament_repo.create_category(
                name=data.name,
                difficulties=[str(d) for d in data.difficulties],
                cycle_frequency=data.cycle_frequency,
                participation_xp=data.participation_xp,
                placement_xp=msgspec.json.encode(data.placement_xp).decode(),
                streak_xp=msgspec.json.encode(data.streak_xp).decode(),
                champion_role_id=data.champion_role_id,
            )
        except UniqueConstraintViolationError as e:
            if "name" in (e.constraint_name or ""):
                raise CategoryNameExistsError(data.name) from e
            raise
        return msgspec.convert(row, TournamentCategoryResponse)

    async def list_categories(self) -> list[TournamentCategoryResponse]:
        """List all tournament categories.

        Returns:
            List of tournament categories ordered by name.
        """
        rows = await self._tournament_repo.fetch_categories()
        return [msgspec.convert(row, TournamentCategoryResponse) for row in rows]

    async def get_category(self, category_id: int) -> TournamentCategoryResponse:
        """Get a single tournament category by ID.

        Args:
            category_id: Category ID.

        Returns:
            Tournament category.

        Raises:
            CategoryNotFoundError: If the category does not exist.
        """
        row = await self._tournament_repo.fetch_category(category_id)
        if row is None:
            raise CategoryNotFoundError(category_id)
        return msgspec.convert(row, TournamentCategoryResponse)

    async def update_category(
        self,
        category_id: int,
        data: TournamentCategoryPatchRequest,
    ) -> TournamentCategoryResponse:
        """Update a tournament category.

        Acquires a connection so the active cycle check and update happen
        on the same connection, preventing TOCTOU races.

        Args:
            category_id: Category ID to update.
            data: Partial category update request.

        Returns:
            Updated tournament category.

        Raises:
            CategoryLockedError: If an active or finalizing cycle exists.
            CategoryNotFoundError: If the category does not exist.
            CategoryNameExistsError: If the updated name already exists.
        """
        updates: dict[str, object] = {}
        if data.name is not msgspec.UNSET:
            updates["name"] = data.name
        if data.difficulties is not msgspec.UNSET:
            updates["difficulties"] = [str(d) for d in data.difficulties]
        if data.cycle_frequency is not msgspec.UNSET:
            updates["cycle_frequency"] = data.cycle_frequency
        if data.participation_xp is not msgspec.UNSET:
            updates["participation_xp"] = data.participation_xp
        if data.placement_xp is not msgspec.UNSET:
            updates["placement_xp"] = msgspec.json.encode(data.placement_xp).decode()
        if data.streak_xp is not msgspec.UNSET:
            updates["streak_xp"] = msgspec.json.encode(data.streak_xp).decode()
        if data.champion_role_id is not msgspec.UNSET:
            updates["champion_role_id"] = data.champion_role_id
        if data.is_active is not msgspec.UNSET:
            updates["is_active"] = data.is_active

        async with self._pool.acquire() as conn:
            cycle_id = await self._tournament_repo.check_active_cycle_for_category(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if cycle_id is not None:
                raise CategoryLockedError(category_id, cycle_id=cycle_id)

            try:
                row = await self._tournament_repo.update_category(
                    category_id,
                    updates,
                    conn=conn,  # type: ignore[arg-type]
                )
            except UniqueConstraintViolationError as e:
                if "name" in (e.constraint_name or ""):
                    name = str(updates.get("name", ""))
                    raise CategoryNameExistsError(name) from e
                raise

        if row is None:
            raise CategoryNotFoundError(category_id)
        return msgspec.convert(row, TournamentCategoryResponse)

    async def delete_category(self, category_id: int) -> None:
        """Delete a tournament category.

        Acquires a connection so the active cycle check and delete happen
        on the same connection, preventing TOCTOU races.

        Args:
            category_id: Category ID to delete.

        Raises:
            CategoryLockedError: If an active or finalizing cycle exists.
            CategoryNotFoundError: If the category does not exist.
        """
        async with self._pool.acquire() as conn:
            cycle_id = await self._tournament_repo.check_active_cycle_for_category(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if cycle_id is not None:
                raise CategoryLockedError(category_id, cycle_id=cycle_id)

            deleted = await self._tournament_repo.delete_category(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
        if not deleted:
            raise CategoryNotFoundError(category_id)


async def provide_tournament_service(
    state: State,
    tournament_repo: TournamentRepository,
) -> TournamentService:
    """Litestar DI provider for tournament service.

    Args:
        state: Application state containing the database pool.
        tournament_repo: Tournament repository instance.

    Returns:
        TournamentService instance.
    """
    return TournamentService(state.db_pool, state, tournament_repo)
