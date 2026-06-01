"""Tournaments v3 controller."""

from __future__ import annotations

from typing import Annotated

import litestar
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    TournamentCategoryPatchRequest,
    TournamentCategoryResponse,
    TournamentChooseMapRequest,
    TournamentConfigPatchRequest,
    TournamentConfigResponse,
    TournamentCycleListResponse,
    TournamentDebugCycleLengthRequest,
    TournamentEditionResponse,
    TournamentLeaderboardEntryResponse,
    TournamentLifecycleResponse,
    TournamentNextCycleResponse,
    TournamentPauseRequest,
    TournamentStreakResponse,
)
from litestar.di import Provide
from litestar.params import Body, Parameter
from litestar.response import Response
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from repository.lootbox_repository import provide_lootbox_repository
from repository.tournaments_repository import provide_tournament_repository
from services.exceptions.tournaments import (
    AlreadyVerifiedError,
    CategoryLockedError,
    CategoryNameExistsError,
    CategoryNotFoundError,
    CycleAlreadyLiveError,
    DebugRouteDisabledError,
    InvalidTimezoneError,
    MapNotEligibleError,
    NoActiveEditionError,
    NoAwaitingResultsEditionError,
    NoEligibleMapsError,
    PendingCycleAlreadyExistsError,
    PendingCycleNotFoundError,
    StreakNotFoundError,
    TournamentCompletionNotFoundError,
)
from services.tournament_reward_service import provide_tournament_reward_service
from services.tournament_service import TournamentService, provide_tournament_service
from utilities.errors import CustomHTTPException


class TournamentsController(litestar.Controller):
    """Tournaments v3 controller."""

    tags = ["Tournaments"]
    path = "/tournaments"
    dependencies = {
        "tournament_repo": Provide(provide_tournament_repository),
        "lootbox_repo": Provide(provide_lootbox_repository),
        "tournament_reward_service": Provide(provide_tournament_reward_service),
        "tournament_service": Provide(provide_tournament_service),
    }

    @litestar.get(
        path="/config",
        summary="Get Tournament Config",
        description="Get global tournament configuration.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_config(
        self,
        tournament_service: TournamentService,
    ) -> TournamentConfigResponse:
        """Get tournament config.

        Args:
            tournament_service: Tournament service.

        Returns:
            Tournament configuration.
        """
        return await tournament_service.get_config()

    @litestar.patch(
        path="/config",
        summary="Update Tournament Config",
        description="Update global tournament configuration fields.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def update_config(
        self,
        tournament_service: TournamentService,
        data: Annotated[TournamentConfigPatchRequest, Body(title="Config Update")],
    ) -> TournamentConfigResponse:
        """Update tournament config.

        This is the GLOBAL config mutation surface: ``cadence`` (D-02) and the grid
        anchor (``anchor_weekday``/``anchor_time``/``anchor_tz``, D-07) are mutated
        here. An invalid ``anchor_tz`` is rejected before persisting (T-12-04/T-12-10)
        so it can never reach the grid-boundary PL/pgSQL ``AT TIME ZONE``.

        Args:
            tournament_service: Tournament service.
            data: Config update request.

        Returns:
            Updated tournament configuration.

        Raises:
            CustomHTTPException: 422 if the supplied anchor timezone is unknown.
        """
        try:
            return await tournament_service.update_config(data)
        except InvalidTimezoneError as e:
            raise CustomHTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

    @litestar.post(
        path="/categories",
        summary="Create Tournament Category",
        description="Create a new tournament category with difficulty groupings.",
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def create_category(
        self,
        tournament_service: TournamentService,
        data: Annotated[TournamentCategoryCreateRequest, Body(title="Category")],
    ) -> TournamentCategoryResponse:
        """Create a tournament category.

        Args:
            tournament_service: Tournament service.
            data: Category creation request.

        Returns:
            Created tournament category.

        Raises:
            CustomHTTPException: 409 if category name already exists.
        """
        try:
            return await tournament_service.create_category(data)
        except CategoryNameExistsError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/categories",
        summary="List Tournament Categories",
        description="List all tournament categories.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def list_categories(
        self,
        tournament_service: TournamentService,
    ) -> list[TournamentCategoryResponse]:
        """List all tournament categories.

        Args:
            tournament_service: Tournament service.

        Returns:
            List of tournament categories.
        """
        return await tournament_service.list_categories()

    @litestar.get(
        path="/categories/{category_id:int}",
        summary="Get Tournament Category",
        description="Get a single tournament category by ID.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_category(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> TournamentCategoryResponse:
        """Get a single tournament category.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            Tournament category.

        Raises:
            CustomHTTPException: 404 if category not found.
        """
        try:
            return await tournament_service.get_category(category_id)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/streaks/{user_id:int}",
        summary="Get User Streak",
        description="Get a single user's tournament participation streak.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_streak(
        self,
        tournament_service: TournamentService,
        user_id: Annotated[int, Parameter(description="User ID")],
    ) -> TournamentStreakResponse:
        """Get a user's tournament participation streak.

        Args:
            tournament_service: Tournament service.
            user_id: User ID.

        Returns:
            User participation streak.

        Raises:
            CustomHTTPException: 404 if no streak record exists for the user.
        """
        try:
            return await tournament_service.get_streak(user_id)
        except StreakNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e

    @litestar.patch(
        path="/categories/{category_id:int}",
        summary="Update Tournament Category",
        description="Update a tournament category's fields.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def update_category(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
        data: Annotated[TournamentCategoryPatchRequest, Body(title="Category Update")],
    ) -> TournamentCategoryResponse:
        """Update a tournament category.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.
            data: Category update request.

        Returns:
            Updated tournament category.

        Raises:
            CustomHTTPException: 404 if category not found, 409 if locked or name conflict.
        """
        try:
            return await tournament_service.update_category(category_id, data)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except (CategoryLockedError, CategoryNameExistsError) as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.delete(
        path="/categories/{category_id:int}",
        summary="Delete Tournament Category",
        description="Delete a tournament category.",
        status_code=HTTP_204_NO_CONTENT,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def delete_category(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> Response[None]:
        """Delete a tournament category.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            Empty response with 204 status.

        Raises:
            CustomHTTPException: 404 if category not found, 409 if locked.
        """
        try:
            await tournament_service.delete_category(category_id)
            return Response(None, status_code=HTTP_204_NO_CONTENT)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except CategoryLockedError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/categories/{category_id:int}/next-cycle",
        summary="Preview Next Cycle",
        description="Preview the pending next cycle for a category.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_next_cycle(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> TournamentNextCycleResponse:
        """Preview the pending next cycle.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            Pending cycle preview with map details.

        Raises:
            CustomHTTPException: 404 if category or pending cycle not found.
        """
        try:
            return await tournament_service.get_next_cycle(category_id)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except PendingCycleNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e

    @litestar.post(
        path="/categories/{category_id:int}/select-map",
        summary="Select Map",
        description="Trigger random map selection for next cycle.",
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def select_map(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> TournamentNextCycleResponse:
        """Trigger random map selection for next cycle.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            Created pending cycle with map details.

        Raises:
            CustomHTTPException: 404 if category not found, 409 if pending exists, 422 if no eligible maps.
        """
        try:
            return await tournament_service.select_map(category_id)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except PendingCycleAlreadyExistsError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e
        except NoEligibleMapsError as e:
            raise CustomHTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

    @litestar.post(
        path="/categories/{category_id:int}/reroll",
        summary="Reroll Map",
        description="Delete current pending cycle and select a new map.",
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def reroll_map(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> TournamentNextCycleResponse:
        """Delete current pending cycle and select a new map.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            New pending cycle with map details.

        Raises:
            CustomHTTPException: 404 if category or pending not found, 422 if no eligible maps.
        """
        try:
            return await tournament_service.reroll_map(category_id)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except PendingCycleNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except NoEligibleMapsError as e:
            raise CustomHTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

    @litestar.patch(
        path="/categories/{category_id:int}/next-cycle",
        summary="Choose Map",
        description="Explicitly set the map for next cycle.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def choose_map(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
        data: Annotated[TournamentChooseMapRequest, Body(title="Choose Map")],
    ) -> TournamentNextCycleResponse:
        """Explicitly set the map for next cycle.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.
            data: Request with the map code.

        Returns:
            Pending cycle with chosen map details.

        Raises:
            CustomHTTPException: 404 if category not found, 422 if map not eligible.
        """
        try:
            return await tournament_service.choose_map(category_id, data)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except MapNotEligibleError as e:
            raise CustomHTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

    @litestar.post(
        path="/bootstrap",
        summary="Bootstrap First Edition",
        description=(
            "Manually activate the FIRST grid-snapped edition (one edition + one child "
            "cycle per active category) so it then rolls over automatically via the "
            "pg_cron transition machinery. Idempotent-safe: an active edition already "
            "existing returns 409. The shared started_at is grid-snapped (never now())."
        ),
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def bootstrap_edition(
        self,
        tournament_service: TournamentService,
    ) -> TournamentEditionResponse:
        """Activate the first grid-snapped edition (config-level, D-13a).

        Bootstrap creates ONE edition spanning all active categories; the timing is
        shared on the edition (started_at/ends_at) rather than per-cycle.

        Args:
            tournament_service: Tournament service.

        Returns:
            The created active edition.

        Raises:
            CustomHTTPException: 409 if an active edition already exists, 422 if a
                category has no eligible maps.
        """
        try:
            return await tournament_service.bootstrap_edition()
        except CycleAlreadyLiveError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e
        except NoEligibleMapsError as e:
            raise CustomHTTPException(
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

    @litestar.patch(
        path="/publish-results",
        summary="Force-Publish Edition Results",
        description=(
            "Admin escape hatch (D-03): force-publish the results of the edition "
            "currently awaiting_results, IGNORING any remaining in-flight "
            "verifications. Computes results from currently-verified runs, writes "
            "the deferred results event, and completes the edition. Abandoned "
            "(still-pending) runs are left pending (audit trail). Returns 409 if no "
            "edition is awaiting results. Requires tournaments:write; the bot-side "
            "mod gate (Plan 05) is the authoritative caller check."
        ),
        status_code=HTTP_204_NO_CONTENT,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def force_publish_results(
        self,
        tournament_service: TournamentService,
    ) -> Response[None]:
        """Force-publish the awaiting_results edition's results (D-03).

        Args:
            tournament_service: Tournament service.

        Returns:
            Empty response with 204 status. The results announcement is delivered
            asynchronously via the deferred ``edition_results`` outbox event drained
            on the poller's next tick (CR-01); there is no synchronous body.

        Raises:
            CustomHTTPException: 409 if no edition is currently awaiting results.
        """
        try:
            await tournament_service.force_publish_results()
            return Response(None, status_code=HTTP_204_NO_CONTENT)
        except NoAwaitingResultsEditionError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.patch(
        path="/pause",
        summary="Pause or Resume Edition Transitions",
        description=(
            "GLOBAL hiatus lever (D-03/D-12): pause (paused=true) or resume "
            "(paused=false) automatic edition transitions. While paused the active "
            "edition still runs its full term; only creation of the NEXT edition is "
            "suppressed at the boundary. Resuming restores the normal cadence."
        ),
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def set_transitions_paused(
        self,
        tournament_service: TournamentService,
        data: Annotated[TournamentPauseRequest, Body(title="Pause")],
    ) -> TournamentLifecycleResponse:
        """Pause or resume automatic edition transitions (GLOBAL).

        Args:
            tournament_service: Tournament service.
            data: Request with the paused flag.

        Returns:
            The updated global lifecycle state.
        """
        return await tournament_service.set_transitions_paused(data.paused)

    @litestar.patch(
        path="/debug-cycle-length",
        summary="Override Edition Length (DEBUG/TEST ONLY)",
        description=(
            "DEBUG/TEST ONLY: override the GLOBAL edition length in seconds so the next "
            "transition recomputes from the override. Pass seconds=null to clear the "
            "override and restore the normal cadence. Rejected in production (T-12-07)."
        ),
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def set_debug_cycle_length(
        self,
        tournament_service: TournamentService,
        data: Annotated[TournamentDebugCycleLengthRequest, Body(title="Debug Cycle Length")],
    ) -> TournamentLifecycleResponse:
        """Override the GLOBAL edition length in seconds (DEBUG/TEST ONLY).

        Args:
            tournament_service: Tournament service.
            data: Request with the seconds override (None clears it).

        Returns:
            The updated global lifecycle state.

        Raises:
            CustomHTTPException: 403 if disabled in production.
        """
        try:
            return await tournament_service.set_debug_cycle_length(data.seconds)
        except DebugRouteDisabledError as e:
            raise CustomHTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/editions/active",
        summary="Get Active Edition",
        description=(
            "Return the single active edition's shared grid-anchored timing "
            "(id/started_at/ends_at/status). ``ends_at`` is STORED, not derived — the "
            "frontend reads it here instead of computing it (D-05/D-08, closes "
            "frontend-spec §8)."
        ),
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_active_edition(
        self,
        tournament_service: TournamentService,
    ) -> TournamentEditionResponse:
        """Return the active edition's stored shared timing.

        Args:
            tournament_service: Tournament service.

        Returns:
            The active edition (id/started_at/ends_at/status/created_at).

        Raises:
            CustomHTTPException: 404 if no edition is currently active.
        """
        edition = await tournament_service.fetch_active_edition()
        if edition is None:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(NoActiveEditionError()),
            )
        return edition

    @litestar.patch(
        path="/completions/{tournament_completion_id:int}/verify",
        summary="Verify Tournament Completion",
        description="Verify a non-PB tournament completion (bot mod-review callback).",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:verify"}},
    )
    async def verify_tournament_completion(
        self,
        request: litestar.Request,
        tournament_service: TournamentService,
        tournament_completion_id: Annotated[int, Parameter(description="Tournament completion ID")],
    ) -> JobStatusResponse:
        """Verify a tournament completion row.

        Args:
            request: HTTP request (for headers forwarded to the publish call).
            tournament_service: Tournament service.
            tournament_completion_id: Tournament completion ID to verify.

        Returns:
            Job status of the published verification-changed event.

        Raises:
            CustomHTTPException: 404 if the tournament completion does not exist.
        """
        try:
            return await tournament_service.verify_tournament_completion(
                tournament_completion_id, headers=request.headers
            )
        except TournamentCompletionNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e

    @litestar.patch(
        path="/completions/{tournament_completion_id:int}/reject",
        summary="Reject Tournament Completion",
        description="Reject a non-PB tournament completion (bot mod-review callback).",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:verify"}},
    )
    async def reject_tournament_completion(
        self,
        request: litestar.Request,
        tournament_service: TournamentService,
        tournament_completion_id: Annotated[int, Parameter(description="Tournament completion ID")],
    ) -> JobStatusResponse:
        """Reject a tournament completion row (leaves it unverified).

        Args:
            request: HTTP request (for headers forwarded to the publish call).
            tournament_service: Tournament service.
            tournament_completion_id: Tournament completion ID to reject.

        Returns:
            Job status of the published verification-changed event.

        Raises:
            CustomHTTPException: 404 if the tournament completion does not exist;
                409 if it is already verified (a verified run is terminal and cannot
                be rejected back to unverified — CR-01).
        """
        try:
            return await tournament_service.reject_tournament_completion(
                tournament_completion_id, headers=request.headers
            )
        except TournamentCompletionNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except AlreadyVerifiedError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/cycles/{cycle_id:int}/leaderboard",
        summary="Get Tournament Leaderboard",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_leaderboard(
        self,
        tournament_service: TournamentService,
        cycle_id: Annotated[int, Parameter(description="Cycle ID")],
    ) -> list[TournamentLeaderboardEntryResponse]:
        """Get the ranked leaderboard for a tournament cycle.

        Args:
            tournament_service: Tournament service.
            cycle_id: Cycle to fetch leaderboard for.

        Returns:
            List of ranked leaderboard entries.
        """
        return await tournament_service.get_leaderboard(cycle_id)

    @litestar.get(
        path="/cycles",
        summary="List Tournament Cycles",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def list_cycles(
        self,
        tournament_service: TournamentService,
        status: Annotated[str | None, Parameter(description="Filter by cycle status", required=False)] = None,
        category_id: Annotated[int | None, Parameter(description="Filter by category ID", required=False)] = None,
        limit: Annotated[int, Parameter(description="Max results", ge=1, le=100)] = 20,
        offset: Annotated[int, Parameter(description="Result offset", ge=0)] = 0,
    ) -> TournamentCycleListResponse:
        """List tournament cycles with optional filters.

        Args:
            tournament_service: Tournament service.
            status: Optional cycle status filter.
            category_id: Optional category ID filter.
            limit: Maximum number of results (1-100).
            offset: Result offset for pagination.

        Returns:
            Paginated cycle list with winner info.
        """
        return await tournament_service.list_cycles(
            status=status,
            category_id=category_id,
            limit=limit,
            offset=offset,
        )
