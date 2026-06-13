"""V3 Skill routes — per-player skill score reads and superuser weight config."""

from __future__ import annotations

from genjishimada_sdk.skill import (
    SkillBreakdownRow,
    SkillConfigUpdateRequest,
    SkillSummaryResponse,
    SkillTiersResponse,
    Weights,
)
from litestar import Controller, get, patch
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

from repository.skill_repository import provide_skill_repository
from services.exceptions.skill import InvalidGammaError
from services.skill_service import SkillService, provide_skill_service


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
        await skill_service.recompute_all()
        return weights
