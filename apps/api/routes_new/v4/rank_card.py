"""V4 RankCard routes."""

from __future__ import annotations

from typing import Annotated

from genjishimada_sdk.rank_card import AvatarResponse, BackgroundResponse, RankCardBadgeSettings, RankCardResponse
from litestar import Controller, get, put
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import HTTP_204_NO_CONTENT
from msgspec import Struct

from repository.rank_card_repository import provide_rank_card_repository
from services.rank_card_service import RankCardService, provide_rank_card_service


class BackgroundBody(Struct):
    """Request body for setting background."""

    name: str


class AvatarSkinBody(Struct):
    """Request body for setting avatar skin."""

    skin: str


class AvatarPoseBody(Struct):
    """Request body for setting avatar pose."""

    pose: str


class RankCardController(Controller):
    """Controller for rank_card endpoints."""

    tags = ["Rank Card"]
    path = "/users/{user_id:int}/rank-card"
    dependencies = {
        "rank_card_repo": Provide(provide_rank_card_repository),
        "rank_card_service": Provide(provide_rank_card_service),
    }

    @get(
        "/",
        summary="Get rank card data",
        description="Return full rank card payload including rank, avatar, badges, map totals, and XP.",
    )
    async def get_rank_card(
        self,
        rank_card_service: RankCardService,
        user_id: int,
    ) -> RankCardResponse:
        """Get the full rank card payload for a user.

        Aggregates rank, nickname, avatar, background, badge settings, per-difficulty
        progress, map/playtest counts, world records, and XP/prestige info.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.

        Returns:
            The complete rank card model ready for rendering (200 OK).
        """
        return await rank_card_service.get_rank_card_data(user_id)

    @get(
        "/background",
        summary="Get background",
        description="Return the user's current rank-card background.",
    )
    async def get_background(
        self,
        rank_card_service: RankCardService,
        user_id: int,
    ) -> BackgroundResponse:
        """Get the user's current rank-card background.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.

        Returns:
            The background name (200 OK).
        """
        return await rank_card_service.get_background(user_id)

    @put(
        "/background",
        summary="Set background",
        description="Set the user's rank-card background by name.",
    )
    async def set_background(
        self,
        rank_card_service: RankCardService,
        user_id: int,
        data: Annotated[BackgroundBody, Body(title="Background request")],
    ) -> BackgroundResponse:
        """Set the user's rank-card background.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.
            data: Payload containing the background name.

        Returns:
            The updated background name (200 OK).
        """
        return await rank_card_service.set_background(user_id, data.name)

    @get(
        "/avatar/skin",
        summary="Get avatar skin",
        description="Return the user's current avatar skin.",
    )
    async def get_avatar_skin(
        self,
        rank_card_service: RankCardService,
        user_id: int,
    ) -> AvatarResponse:
        """Get the user's current avatar skin.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.

        Returns:
            The avatar skin (200 OK).
        """
        return await rank_card_service.get_avatar_skin(user_id)

    @put(
        "/avatar/skin",
        summary="Set avatar skin",
        description="Set the user's avatar skin by name.",
    )
    async def set_avatar_skin(
        self,
        rank_card_service: RankCardService,
        user_id: int,
        data: Annotated[AvatarSkinBody, Body(title="Avatar skin request")],
    ) -> AvatarResponse:
        """Set the user's avatar skin.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.
            data: Payload containing the skin name.

        Returns:
            The updated avatar skin (200 OK).
        """
        return await rank_card_service.set_avatar_skin(user_id, data.skin)

    @get(
        "/avatar/pose",
        summary="Get avatar pose",
        description="Return the user's current avatar pose.",
    )
    async def get_avatar_pose(
        self,
        rank_card_service: RankCardService,
        user_id: int,
    ) -> AvatarResponse:
        """Get the user's current avatar pose.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.

        Returns:
            The avatar pose (200 OK).
        """
        return await rank_card_service.get_avatar_pose(user_id)

    @put(
        "/avatar/pose",
        summary="Set avatar pose",
        description="Set the user's avatar pose by name.",
    )
    async def set_avatar_pose(
        self,
        rank_card_service: RankCardService,
        user_id: int,
        data: Annotated[AvatarPoseBody, Body(title="Avatar pose request")],
    ) -> AvatarResponse:
        """Set the user's avatar pose.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.
            data: Payload containing the pose name.

        Returns:
            The updated avatar pose (200 OK).
        """
        return await rank_card_service.set_avatar_pose(user_id, data.pose)

    @get(
        "/badges",
        summary="Get badge settings",
        description="Return the user's badge settings with resolved URLs (e.g., mastery, spray).",
    )
    async def get_badges(
        self,
        rank_card_service: RankCardService,
        user_id: int,
    ) -> RankCardBadgeSettings:
        """Get the user's badge settings.

        Resolves URLs for supported badge types (e.g., mastery and spray).

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.

        Returns:
            Badge names/types/URLs for slots 1-6 (200 OK).
        """
        return await rank_card_service.get_badges(user_id)

    @put(
        "/badges",
        summary="Set badge settings",
        description="Set all badge slots (1-6) for the user. The user_id in the payload is ignored if provided.",
    )
    async def set_badges(
        self,
        rank_card_service: RankCardService,
        user_id: int,
        data: Annotated[RankCardBadgeSettings, Body(title="Badge settings request")],
    ) -> Response:
        """Set the user's badge settings for slots 1-6.

        All slots are upserted atomically. To clear a slot, set its badge_name
        and badge_type to null. Any user_id field included in the payload
        is ignored; the path parameter is authoritative.

        Args:
            rank_card_service: Service dependency.
            user_id: Target user ID from the URL path.
            data: Badge settings payload for slots 1-6.

        Returns:
            Empty response with 204 No Content.
        """
        await rank_card_service.set_badges(user_id, data)
        return Response(None, status_code=HTTP_204_NO_CONTENT)
