"""Service for tournament domain business logic."""

from __future__ import annotations

import re
from logging import getLogger
from typing import TYPE_CHECKING

import msgspec
from asyncpg import Pool
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    TournamentCategoryPatchRequest,
    TournamentCategoryResponse,
    TournamentChooseMapRequest,
    TournamentCompletionCreateRequest,
    TournamentCompletionResponse,
    TournamentConfigPatchRequest,
    TournamentConfigResponse,
    TournamentCycleListResponse,
    TournamentCycleWithWinnerResponse,
    TournamentLeaderboardEntryResponse,
    TournamentNextCycleResponse,
    TournamentStreakResponse,
    TournamentVerificationChangedEvent,
)
from litestar.datastructures import Headers, State

from repository.exceptions import UniqueConstraintViolationError
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.exceptions.tournaments import (
    CategoryLockedError,
    CategoryNameExistsError,
    CategoryNotFoundError,
    CycleNotActiveError,
    CycleNotFoundError,
    MapNotEligibleError,
    NoEligibleMapsError,
    PendingCycleAlreadyExistsError,
    PendingCycleNotFoundError,
    SlowerTimeError,
    StreakNotFoundError,
    TournamentCompletionNotFoundError,
)
from services.tournament_reward_service import TournamentRewardService

if TYPE_CHECKING:
    from asyncpg import Connection
    from genjishimada_sdk.xp import XpGrantEvent

log = getLogger(__name__)


class TournamentService(BaseService):
    """Service for tournament config and category business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        tournament_repo: TournamentRepository,
        reward_service: TournamentRewardService | None = None,
    ) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            tournament_repo: Tournament repository instance.
            reward_service: Reward service for participation XP grants. Optional so
                existing unit tests can construct the service without it; the DI
                provider always supplies one in production.
        """
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo
        self._reward_service = reward_service

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

    async def get_streak(self, user_id: int) -> TournamentStreakResponse:
        """Get a single user's participation streak.

        Args:
            user_id: User ID.

        Returns:
            User participation streak.

        Raises:
            StreakNotFoundError: If no streak record exists for the user.
        """
        row = await self._tournament_repo.fetch_streak(user_id)
        if row is None:
            raise StreakNotFoundError(user_id)
        return msgspec.convert(row, TournamentStreakResponse)

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

    async def select_map(self, category_id: int) -> TournamentNextCycleResponse:
        """Trigger random map selection for the next cycle.

        Acquires a connection so the pending-check, config fetch, map selection,
        and cycle creation all happen on the same connection, preventing TOCTOU races.

        Args:
            category_id: Category ID to select a map for.

        Returns:
            Pending cycle preview with joined map details.

        Raises:
            PendingCycleAlreadyExistsError: If a pending cycle already exists.
            CategoryNotFoundError: If the category does not exist.
            NoEligibleMapsError: If no eligible maps are found and LRU fallback also fails.
        """
        async with self._pool.acquire() as conn:
            existing = await self._tournament_repo.fetch_pending_cycle(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if existing is not None:
                raise PendingCycleAlreadyExistsError(category_id)

            config = await self._tournament_repo.fetch_config(
                conn=conn,  # type: ignore[arg-type]
            )

            category = await self._tournament_repo.fetch_category(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if category is None:
                raise CategoryNotFoundError(category_id)

            eligible = await self._tournament_repo.fetch_eligible_maps(
                category["difficulties"],
                config["blacklist_weeks"],
                conn=conn,  # type: ignore[arg-type]
            )

            if eligible:
                selected = eligible[0]
            else:
                log.warning("[!] Eligible map pool exhausted for category %s, using LRU fallback", category_id)
                selected = await self._tournament_repo.fetch_least_recently_used_map(
                    category["difficulties"],
                    conn=conn,  # type: ignore[arg-type]
                )
                if selected is None:
                    raise NoEligibleMapsError(category_id)

            await self._tournament_repo.create_cycle(
                category_id,
                selected["id"],
                conn=conn,  # type: ignore[arg-type]
            )

            result = await self._tournament_repo.fetch_pending_cycle(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )

        return msgspec.convert(result, TournamentNextCycleResponse)

    async def get_next_cycle(self, category_id: int) -> TournamentNextCycleResponse:
        """Preview the pending next cycle for a category.

        Args:
            category_id: Category ID to look up.

        Returns:
            Pending cycle preview with joined map details.

        Raises:
            CategoryNotFoundError: If the category does not exist.
            PendingCycleNotFoundError: If no pending cycle exists.
        """
        category = await self._tournament_repo.fetch_category(category_id)
        if category is None:
            raise CategoryNotFoundError(category_id)

        row = await self._tournament_repo.fetch_pending_cycle(category_id)
        if row is None:
            raise PendingCycleNotFoundError(category_id)

        return msgspec.convert(row, TournamentNextCycleResponse)

    async def reroll_map(self, category_id: int) -> TournamentNextCycleResponse:
        """Delete the current pending cycle and select a new map.

        Acquires a connection so all operations happen atomically.

        Args:
            category_id: Category ID to reroll for.

        Returns:
            New pending cycle preview with joined map details.

        Raises:
            CategoryNotFoundError: If the category does not exist.
            PendingCycleNotFoundError: If no pending cycle exists to reroll.
            NoEligibleMapsError: If no eligible maps are found and LRU fallback also fails.
        """
        async with self._pool.acquire() as conn:
            category = await self._tournament_repo.fetch_category(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if category is None:
                raise CategoryNotFoundError(category_id)

            existing = await self._tournament_repo.fetch_pending_cycle(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if existing is None:
                raise PendingCycleNotFoundError(category_id)

            old_map_id = existing["map_id"]
            old_cycle_id = existing["id"]

            await self._tournament_repo.delete_cycle(
                old_cycle_id,
                conn=conn,  # type: ignore[arg-type]
            )

            config = await self._tournament_repo.fetch_config(
                conn=conn,  # type: ignore[arg-type]
            )

            eligible = await self._tournament_repo.fetch_eligible_maps(
                category["difficulties"],
                config["blacklist_weeks"],
                exclude_map_ids=[old_map_id],
                conn=conn,  # type: ignore[arg-type]
            )

            if eligible:
                selected = eligible[0]
            else:
                log.warning("[!] Eligible map pool exhausted for category %s, using LRU fallback", category_id)
                selected = await self._tournament_repo.fetch_least_recently_used_map(
                    category["difficulties"],
                    conn=conn,  # type: ignore[arg-type]
                )
                if selected is None:
                    raise NoEligibleMapsError(category_id)

            await self._tournament_repo.create_cycle(
                category_id,
                selected["id"],
                conn=conn,  # type: ignore[arg-type]
            )

            result = await self._tournament_repo.fetch_pending_cycle(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )

        return msgspec.convert(result, TournamentNextCycleResponse)

    async def choose_map(
        self,
        category_id: int,
        data: TournamentChooseMapRequest,
    ) -> TournamentNextCycleResponse:
        """Explicitly set the map for the next cycle.

        Validates the map exists and its difficulty matches the category,
        then creates (or replaces) the pending cycle.

        Args:
            category_id: Category ID to set the map for.
            data: Request containing the map code.

        Returns:
            Pending cycle preview with joined map details.

        Raises:
            CategoryNotFoundError: If the category does not exist.
            MapNotEligibleError: If the map is not found or its difficulty doesn't match.
        """
        async with self._pool.acquire() as conn:
            category = await self._tournament_repo.fetch_category(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if category is None:
                raise CategoryNotFoundError(category_id)

            map_row = await self._tournament_repo.fetch_map_by_code(
                data.map_code,
                conn=conn,  # type: ignore[arg-type]
            )
            if map_row is None:
                raise MapNotEligibleError(0, reason=f"Map with code '{data.map_code}' not found.")

            base_difficulty = re.sub(r"\s*[-+]\s*$", "", map_row["difficulty"])
            if base_difficulty not in category["difficulties"]:
                raise MapNotEligibleError(
                    map_row["id"],
                    reason=f"Map difficulty '{map_row['difficulty']}' does not match category difficulties.",
                )

            existing = await self._tournament_repo.fetch_pending_cycle(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if existing is not None:
                await self._tournament_repo.delete_cycle(
                    existing["id"],
                    conn=conn,  # type: ignore[arg-type]
                )

            await self._tournament_repo.create_cycle(
                category_id,
                map_row["id"],
                conn=conn,  # type: ignore[arg-type]
            )

            result = await self._tournament_repo.fetch_pending_cycle(
                category_id,
                conn=conn,  # type: ignore[arg-type]
            )

        return msgspec.convert(result, TournamentNextCycleResponse)

    async def submit_completion(
        self,
        cycle_id: int,
        data: TournamentCompletionCreateRequest,
    ) -> TournamentCompletionResponse:
        """Submit a tournament completion for a cycle.

        Validates the cycle is active, checks if the submitted time is faster
        than the user's current best, inserts the tournament completion, and
        cross-writes to core.completions -- all within a single transaction.

        Args:
            cycle_id: Cycle to submit for.
            data: Completion submission data.

        Returns:
            Created tournament completion.

        Raises:
            CycleNotFoundError: If the cycle does not exist.
            CycleNotActiveError: If the cycle is not active.
            SlowerTimeError: If submitted time is not faster than current best.
        """
        pending_xp_events: list[XpGrantEvent] = []
        async with self._pool.acquire() as conn, conn.transaction():
            cycle = await self._tournament_repo.fetch_cycle(
                cycle_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if cycle is None:
                raise CycleNotFoundError(cycle_id)
            if cycle["status"] != "active":
                raise CycleNotActiveError(cycle_id, cycle["status"])

            existing = await self._tournament_repo.fetch_user_completion(
                cycle_id,
                data.user_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if existing is not None and data.time >= existing["time"]:
                raise SlowerTimeError(current_best=existing["time"], submitted_time=data.time)

            is_first_completion = existing is None

            row = await self._tournament_repo.create_tournament_completion(
                cycle_id=cycle_id,
                user_id=data.user_id,
                map_id=cycle["map_id"],
                time=data.time,
                screenshot=data.screenshot,
                video=data.video,
                conn=conn,  # type: ignore[arg-type]
            )

            await self._tournament_repo.cross_write_to_core(
                tournament_completion_id=row["id"],
                user_id=data.user_id,
                map_id=cycle["map_id"],
                time=data.time,
                screenshot=data.screenshot,
                video=data.video,
                conn=conn,  # type: ignore[arg-type]
            )

            log.info("[->] Tournament completion submitted for cycle %s by user %s", cycle_id, data.user_id)

            # RWD-01: grant participation XP once per (cycle, user). The
            # existing-is-None gate is the "first ever this cycle" signal (the
            # insert above happens after the check); the 08-01 ledger makes a
            # replay a no-op even if this path were reached again. The grant runs
            # inside this open transaction so the ledger claim + lootbox.xp upsert
            # + completion insert commit (or roll back) together. The xp.grant
            # NOTIFICATION is deferred (collected here) and published only after
            # this transaction commits, so a rollback never tells the bot about XP
            # that was erased (CR-02).
            if is_first_completion and self._reward_service is not None:
                pending_xp_events = await self._reward_service.award_participation(
                    cycle=cycle,
                    user_id=data.user_id,
                    conn=conn,  # type: ignore[arg-type]
                )
                log.info("[✓] Participation XP granted for cycle %s to user %s", cycle_id, data.user_id)

        # Transaction committed: now safe to publish the XP grant notification.
        if pending_xp_events and self._reward_service is not None:
            await self._reward_service.publish_xp_events(pending_xp_events)

        return msgspec.convert(row, TournamentCompletionResponse)

    async def verify_tournament_completion(
        self,
        tournament_completion_id: int,
        *,
        headers: Headers | None = None,
        conn: Connection | None = None,
    ) -> JobStatusResponse:
        """Verify a non-PB tournament completion and award participation XP.

        This is the tournament row's OWN verification (D-04): a slower-than-PB run
        has no core completion, so it never fires a core verification event. The
        verdict flips ``tournaments.completions.verified`` TRUE, the first verified
        run auto-enrolls the player by granting participation XP (D-02/D-06,
        idempotent via the 08-01 ledger), and a verified=True
        TournamentVerificationChangedEvent is published. When ``conn`` is None a
        fresh connection + transaction is acquired so the flip + XP grant are
        atomic (mirrors verify_completion_with_pool); the deferred XP notification
        is flushed only after the transaction commits (CR-02).

        Args:
            tournament_completion_id: ID of the tournament completion row to verify.
            headers: Optional request headers forwarded to the publish call
                (carries X-PYTEST-ENABLED in tests so the broker is skipped).
            conn: Optional connection for transaction support.

        Returns:
            Job status of the published verification-changed event.

        Raises:
            TournamentCompletionNotFoundError: If no tournament completion row matches.
        """
        return await self._set_verified(
            tournament_completion_id,
            verified=True,
            idempotency_key=f"tournament:verify:{tournament_completion_id}",
            award_xp=True,
            headers=headers,
            conn=conn,
        )

    async def reject_tournament_completion(
        self,
        tournament_completion_id: int,
        *,
        headers: Headers | None = None,
        conn: Connection | None = None,
    ) -> JobStatusResponse:
        """Reject a non-PB tournament completion (leaves it unverified).

        The simplest reject (Open-Q1): the row stays ``verified = FALSE`` so it
        ranks below verified runs. No participation XP is granted, and a
        verified=False TournamentVerificationChangedEvent is published.

        Args:
            tournament_completion_id: ID of the tournament completion row to reject.
            headers: Optional request headers forwarded to the publish call
                (carries X-PYTEST-ENABLED in tests so the broker is skipped).
            conn: Optional connection for transaction support.

        Returns:
            Job status of the published verification-changed event.

        Raises:
            TournamentCompletionNotFoundError: If no tournament completion row matches.
        """
        return await self._set_verified(
            tournament_completion_id,
            verified=False,
            idempotency_key=f"tournament:reject:{tournament_completion_id}",
            award_xp=False,
            headers=headers,
            conn=conn,
        )

    async def _set_verified(  # noqa: PLR0913
        self,
        tournament_completion_id: int,
        *,
        verified: bool,
        idempotency_key: str,
        award_xp: bool,
        headers: Headers | None = None,
        conn: Connection | None = None,
    ) -> JobStatusResponse:
        """Shared verify/reject body: flip the row, optionally award XP, publish.

        Args:
            tournament_completion_id: Tournament completion row ID.
            verified: Target verified value (True verify, False reject).
            idempotency_key: Publish idempotency key for the changed event.
            award_xp: Whether to award participation XP (verify only).
            headers: Optional request headers forwarded to the publish call.
            conn: Optional connection for transaction support.

        Returns:
            Job status of the published verification-changed event.

        Raises:
            TournamentCompletionNotFoundError: If no tournament completion row matches.
        """
        existing = await self._tournament_repo.fetch_tournament_completion(
            tournament_completion_id,
            conn=conn,  # type: ignore[arg-type]
        )
        if existing is None:
            raise TournamentCompletionNotFoundError(tournament_completion_id)

        pending_xp_events: list[XpGrantEvent] = []

        async def _do(active_conn: Connection) -> dict | None:
            nonlocal pending_xp_events
            row = await self._tournament_repo.set_tournament_verified(
                tournament_completion_id,
                verified,
                conn=active_conn,
            )
            if award_xp and self._reward_service is not None and row is not None:
                cycle = await self._tournament_repo.fetch_cycle(row["cycle_id"], conn=active_conn)
                if cycle is not None:
                    pending_xp_events = await self._reward_service.award_participation(
                        cycle=cycle,
                        user_id=row["user_id"],
                        conn=active_conn,
                    )
            return row

        if conn is None:
            async with self._pool.acquire() as raw_conn, raw_conn.transaction():
                updated = await _do(raw_conn)  # type: ignore[arg-type]
        else:
            updated = await _do(conn)

        # Transaction committed: now safe to publish the deferred XP notification.
        if pending_xp_events and self._reward_service is not None:
            await self._reward_service.publish_xp_events(pending_xp_events)

        time_value = float(updated["time"]) if updated else float(existing["time"])
        event = TournamentVerificationChangedEvent(
            tournament_completion_id=tournament_completion_id,
            cycle_id=existing["cycle_id"],
            user_id=existing["user_id"],
            verified=verified,
            time=time_value,
        )
        return await self.publish_message(
            routing_key="api.tournament.verification.changed",
            data=event,
            headers=headers if headers is not None else Headers(),
            idempotency_key=idempotency_key,
        )

    async def get_leaderboard(self, cycle_id: int) -> list[TournamentLeaderboardEntryResponse]:
        """Get the ranked leaderboard for a tournament cycle.

        Args:
            cycle_id: Cycle to fetch leaderboard for.

        Returns:
            List of ranked leaderboard entries.
        """
        rows = await self._tournament_repo.fetch_leaderboard(cycle_id)
        return [msgspec.convert(row, TournamentLeaderboardEntryResponse) for row in rows]

    async def list_cycles(
        self,
        *,
        status: str | None = None,
        category_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> TournamentCycleListResponse:
        """List tournament cycles with optional filters and winner info.

        Args:
            status: Optional cycle status filter.
            category_id: Optional category ID filter.
            limit: Maximum number of results.
            offset: Result offset for pagination.

        Returns:
            Paginated cycle list with winner info.
        """
        total, rows = await self._tournament_repo.fetch_cycles(
            status=status,
            category_id=category_id,
            limit=limit,
            offset=offset,
        )
        return TournamentCycleListResponse(
            total=total,
            cycles=[msgspec.convert(row, TournamentCycleWithWinnerResponse) for row in rows],
        )


async def provide_tournament_service(
    state: State,
    tournament_repo: TournamentRepository,
    tournament_reward_service: TournamentRewardService,
) -> TournamentService:
    """Litestar DI provider for tournament service.

    Args:
        state: Application state containing the database pool.
        tournament_repo: Tournament repository instance.
        tournament_reward_service: Reward service for participation XP grants,
            resolved from the controller's dependencies dict.

    Returns:
        TournamentService instance.
    """
    return TournamentService(state.db_pool, state, tournament_repo, tournament_reward_service)
