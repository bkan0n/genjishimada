"""V3 Skill routes — per-player skill score reads and superuser weight config."""

from __future__ import annotations

from typing import Annotated, Literal

from genjishimada_sdk.skill import (
    SkillBreakdownRow,
    SkillChangeDetailResponse,
    SkillChangeFeedItem,
    SkillConfigUpdateRequest,
    SkillHistoryResponse,
    SkillSummaryResponse,
    SkillTiersResponse,
    SkillTiersUpdateRequest,
    Weights,
)
from litestar import Controller, get, patch
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.params import Parameter
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_422_UNPROCESSABLE_ENTITY

from repository.skill_repository import provide_skill_repository
from services.exceptions.skill import InvalidGammaError, InvalidPercentilesError
from services.skill_service import SkillService, TriggerDescriptor, provide_skill_service

# Time-window literal for the dashboard reads. msgspec rejects any value outside this closed
# set at decode (T-14-13) → 4xx; the value is never interpolated into SQL (the service maps it
# to a `captured_at` lower bound via a fixed dict).
Window = Literal["7d", "30d", "90d", "1y", "all"]


class SkillController(Controller):
    """Endpoints for per-player skill scores and weight configuration."""

    path = "/skill"
    tags = ["Skill"]
    dependencies = {
        "skill_repo": Provide(provide_skill_repository),
        "skill_service": Provide(provide_skill_service),
    }

    @get(
        path="/users/{user_id:int}",
        summary="Get User Skill Summary",
        description=(
            "Return the player's aggregate skill score and summary counts. "
            "A player with no eligible runs returns score 0 with a zero summary (D-07)."
        ),
    )
    async def get_user_skill(self, skill_service: SkillService, user_id: int) -> SkillSummaryResponse:
        """Return the player's skill summary.

        Args:
            skill_service: Skill service dependency.
            user_id: Discord user ID.

        Returns:
            SkillSummaryResponse: The player's summary (all-zero when no snapshot row exists).
        """
        return await skill_service.get_user_skill(user_id)

    @get(
        path="/users/{user_id:int}/breakdown",
        summary="Get User Skill Breakdown",
        description=(
            "Return the per-map breakdown captured during recompute (D-06): per-map raw "
            "score, gamma-decayed contribution, and medal/WR/video badges. Empty list for "
            "a player with no eligible runs (D-07)."
        ),
    )
    async def get_user_breakdown(self, skill_service: SkillService, user_id: int) -> list[SkillBreakdownRow]:
        """Return the player's per-map skill breakdown.

        Args:
            skill_service: Skill service dependency.
            user_id: Discord user ID.

        Returns:
            list[SkillBreakdownRow]: Per-map breakdown rows ([] for a zero-eligible player).
        """
        return await skill_service.get_user_breakdown(user_id)

    @get(
        path="/users/{user_id:int}/history",
        summary="Get User Skill History",
        description=(
            "Return the player's time-windowed score history (oldest-first points) plus a "
            "summary (best/lowest/average, first-vs-last point and percent change). A player "
            "with no history returns an empty points list and a zeroed summary (never 500). An "
            "unknown window value is rejected at decode (4xx)."
        ),
    )
    async def get_history(
        self,
        skill_service: SkillService,
        user_id: int,
        window: Annotated[Window, Parameter(description="Time window (7d/30d/90d/1y/all)")] = "all",
    ) -> SkillHistoryResponse:
        """Return the player's windowed score history + summary (SPEC req 3/6/7).

        Args:
            skill_service: Skill service dependency.
            user_id: Discord user ID.
            window: Lookback window; ``all`` returns every point. An unknown value is
                rejected by msgspec at decode (4xx).

        Returns:
            SkillHistoryResponse: Ordered points + window summary (empty/zero for a player
                with no history).
        """
        return await skill_service.get_user_history(user_id, window)

    @get(
        path="/users/{user_id:int}/changes",
        summary="Get User Skill Change Feed",
        description=(
            "Return the player's newest-first paginated change feed (delta + cause_category + "
            "description per recompute that touched them). A player with no changes returns an "
            "empty list. An unknown window value is rejected at decode (4xx)."
        ),
    )
    async def get_changes(
        self,
        skill_service: SkillService,
        user_id: int,
        window: Annotated[Window, Parameter(description="Time window (7d/30d/90d/1y/all)")] = "all",
        limit: Annotated[int, Parameter(description="Max results", ge=1, le=100)] = 20,
        offset: Annotated[int, Parameter(description="Result offset", ge=0)] = 0,
    ) -> list[SkillChangeFeedItem]:
        """Return the player's newest-first paginated change feed (SPEC req 4/6/7).

        Args:
            skill_service: Skill service dependency.
            user_id: Discord user ID.
            window: Lookback window; ``all`` returns every change.
            limit: Maximum number of results (1-100); caps the page size (T-14-14).
            offset: Result offset for pagination.

        Returns:
            list[SkillChangeFeedItem]: Newest-first feed items ([] for a player with no
                changes).
        """
        return await skill_service.get_user_changes(user_id, window, limit, offset)

    @get(
        path="/users/{user_id:int}/changes/{change_id:int}",
        summary="Get Skill Change Detail",
        description=(
            "Return the drill-down for a single change: previous/new/delta, the top-5 per-map "
            "contributors (main_causes), and the summed remaining tail (other_factors), with "
            "sum(main_causes.impact) + other_factors == delta within 1e-6 (D-06/D-07). A "
            "change_id that does not belong to the user (or does not exist) returns 404."
        ),
    )
    async def get_change_detail(
        self,
        skill_service: SkillService,
        user_id: int,
        change_id: int,
    ) -> SkillChangeDetailResponse:
        """Return the per-change drill-down (SPEC req 5; IDOR-mitigated 404, T-14-06).

        The service performs an ownership-checked lookup (``change_id`` AND ``user_id``); a
        foreign or unknown change_id yields ``None`` here, which this handler converts to a
        404 (not 403 — no existence confirmation, ASVS V4).

        Args:
            skill_service: Skill service dependency.
            user_id: Discord user ID that must own the change.
            change_id: The change record to read.

        Returns:
            SkillChangeDetailResponse: The change drill-down.

        Raises:
            HTTPException: 404 if no change with that id belongs to the user.
        """
        detail = await skill_service.get_user_change_detail(user_id, change_id)
        if detail is None:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="change not found")
        return detail

    @get(
        path="/tiers",
        summary="Get Skill Tier Config",
        description=(
            "Return the current tier boundaries, configured percentiles, and computed_at "
            "for rendering a tier legend. Public read; no new scope."
        ),
    )
    async def get_tiers(self, skill_service: SkillService) -> SkillTiersResponse:
        """Return the current tier legend (PYO-TIER-05).

        Args:
            skill_service: Skill service dependency.

        Returns:
            SkillTiersResponse: The current boundaries, percentiles, and computed_at.
        """
        return await skill_service.get_tier_config()

    @patch(
        path="/tiers",
        summary="Update Skill Tier Percentiles",
        description=(
            "Update the tier percentiles (superuser only) and immediately re-derive the "
            "boundaries from the current snapshot — scores are unchanged (U82-TIER-PATCH-01). "
            "Invalid percentiles return 400 and persist nothing."
        ),
        opt={"required_scopes": {"skill:admin"}},
    )
    async def update_tiers(
        self,
        skill_service: SkillService,
        data: SkillTiersUpdateRequest,
    ) -> SkillTiersResponse:
        """Update the tier percentiles then re-derive boundaries (superuser only, U82-TIER-PATCH-01).

        Gated by the SAME ``skill:admin`` sentinel ``update_config`` uses — no new scope is
        minted; it is a guard sentinel no normal token holds, so a superuser bypasses the
        guard while any non-superuser is rejected 401/403. On invalid percentiles nothing is
        persisted (the 400 is raised before any write).

        Args:
            skill_service: Skill service dependency.
            data: The replacement percentiles body.

        Returns:
            SkillTiersResponse: The updated boundaries, percentiles, and computed_at.

        Raises:
            HTTPException: 400 if the percentiles are not exactly 6 values strictly within
                (0, 1) and strictly increasing.
        """
        try:
            return await skill_service.update_tier_config(data.percentiles)
        except InvalidPercentilesError as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e)) from e

    @get(
        path="/config",
        summary="Get Skill Weights",
        description="Return the current skill-score tuning weights from the DB config.",
    )
    async def get_config(self, skill_service: SkillService) -> Weights:
        """Return the current skill weight configuration.

        Args:
            skill_service: Skill service dependency.

        Returns:
            Weights: The current tuning weights.
        """
        return await skill_service.get_weights()

    @patch(
        path="/config",
        summary="Update Skill Weights",
        description=(
            "Update the skill-score tuning weights (superuser only) and immediately trigger "
            "a full recompute so scores reflect the new weights right away (D-10)."
        ),
        opt={"required_scopes": {"skill:admin"}},
    )
    async def update_config(
        self,
        skill_service: SkillService,
        data: SkillConfigUpdateRequest,
    ) -> Weights:
        """Update the weight config then immediately recompute (superuser only, D-10).

        The ``required_scopes`` sentinel no normal token holds means a superuser bypasses
        the guard while any non-superuser is rejected 401/403 (SPEC req 7; no new scope
        is minted — ``skill:admin`` is a guard sentinel, not a granted scope).

        Args:
            skill_service: Skill service dependency.
            data: Partial PATCH body of weight overrides.

        Returns:
            Weights: The rebuilt weight config.

        Raises:
            HTTPException: 422 if gamma is set below the safe floor (0.5).
        """
        try:
            weights = await skill_service.update_weights(data)
        except InvalidGammaError as e:
            raise HTTPException(status_code=HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        await skill_service.recompute_all(TriggerDescriptor(cause_category="SYSTEM"))
        return weights
