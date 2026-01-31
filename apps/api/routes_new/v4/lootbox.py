"""Lootbox v4 controller."""

from __future__ import annotations

from typing import Annotated

import litestar
from genjishimada_sdk.lootbox import (
    LootboxKeyType,
    LootboxKeyTypeResponse,
    RewardTypeResponse,
    UserLootboxKeyAmountResponse,
    UserRewardResponse,
)
from genjishimada_sdk.maps import XPMultiplierRequest
from genjishimada_sdk.xp import TierChangeResponse, XpGrantRequest, XpGrantResponse
from litestar.datastructures import State
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_204_NO_CONTENT, HTTP_400_BAD_REQUEST

from repository.lootbox_repository import LootboxRepository
from services.exceptions.lootbox import InsufficientKeysError
from services.lootbox_service import LootboxService
from utilities.errors import CustomHTTPException


async def provide_lootbox_repository(state: State) -> LootboxRepository:
    """Provide lootbox repository.

    Args:
        state: Application state.

    Returns:
        LootboxRepository instance.
    """
    return LootboxRepository(pool=state.db_pool)


async def provide_lootbox_service(state: State, lootbox_repo: LootboxRepository) -> LootboxService:
    """Provide lootbox service.

    Args:
        state: Application state.
        lootbox_repo: Lootbox repository instance.

    Returns:
        LootboxService instance.
    """
    return LootboxService(pool=state.db_pool, state=state, lootbox_repo=lootbox_repo)


class LootboxController(litestar.Controller):
    """Lootbox v4 controller."""

    tags = ["Lootbox"]
    path = "/lootbox"
    dependencies = {
        "lootbox_repo": Provide(provide_lootbox_repository),
        "lootbox_service": Provide(provide_lootbox_service),
    }

    @litestar.get(
        path="/rewards",
        summary="List All Rewards",
        description="Get all possible rewards with optional filters.",
    )
    async def view_all_rewards(
        self,
        lootbox_service: LootboxService,
        reward_type: str | None = None,
        key_type: LootboxKeyType | None = None,
        rarity: str | None = None,
    ) -> list[RewardTypeResponse]:
        """Get all possible rewards.

        Args:
            lootbox_service: Lootbox service.
            reward_type: Optional filter by reward type.
            key_type: Optional filter by key type.
            rarity: Optional filter by rarity.

        Returns:
            List of reward definitions.
        """
        return await lootbox_service.view_all_rewards(reward_type=reward_type, key_type=key_type, rarity=rarity)

    @litestar.get(
        path="/keys",
        summary="List All Key Types",
        description="Get all possible key types with optional filter.",
    )
    async def view_all_keys(
        self,
        lootbox_service: LootboxService,
        key_type: LootboxKeyType | None = None,
    ) -> list[LootboxKeyTypeResponse]:
        """Get all possible key types.

        Args:
            lootbox_service: Lootbox service.
            key_type: Optional filter by key type.

        Returns:
            List of key type definitions.
        """
        return await lootbox_service.view_all_keys(key_type=key_type)

    @litestar.get(
        path="/users/{user_id:int}/rewards",
        summary="Get User Rewards",
        description="Get all rewards earned by a user.",
    )
    async def view_user_rewards(
        self,
        lootbox_service: LootboxService,
        user_id: int,
        reward_type: str | None = None,
        key_type: LootboxKeyType | None = None,
        rarity: str | None = None,
    ) -> list[UserRewardResponse]:
        """Get all rewards earned by a user.

        Args:
            lootbox_service: Lootbox service.
            user_id: Target user ID.
            reward_type: Optional filter by reward type.
            key_type: Optional filter by key type.
            rarity: Optional filter by rarity.

        Returns:
            List of user rewards.
        """
        return await lootbox_service.view_user_rewards(
            user_id=user_id, reward_type=reward_type, key_type=key_type, rarity=rarity
        )

    @litestar.get(
        path="/users/{user_id:int}/keys",
        summary="Get User Keys",
        description="Get keys owned by a user grouped by key type.",
    )
    async def view_user_keys(
        self,
        lootbox_service: LootboxService,
        user_id: int,
        key_type: LootboxKeyType | None = None,
    ) -> list[UserLootboxKeyAmountResponse]:
        """Get keys owned by a user.

        Args:
            lootbox_service: Lootbox service.
            user_id: Target user ID.
            key_type: Optional filter by key type.

        Returns:
            List of key counts by type.
        """
        return await lootbox_service.view_user_keys(user_id=user_id, key_type=key_type)

    @litestar.get(
        path="/users/{user_id:int}/keys/{key_type:str}",
        summary="Draw Random Rewards",
        description="Get random rewards using gacha system.",
    )
    async def get_random_items(
        self,
        lootbox_service: LootboxService,
        request: litestar.Request,
        user_id: int,
        key_type: LootboxKeyType,
        amount: int = 1,
    ) -> list[RewardTypeResponse]:
        """Get random rewards using gacha system.

        Args:
            lootbox_service: Lootbox service.
            request: Request object.
            user_id: Target user ID.
            key_type: Key type to use.
            amount: Number of items to grant (1-3).

        Returns:
            List of granted rewards.

        Raises:
            CustomHTTPException: If user has insufficient keys.
        """
        test_mode = bool(request.headers.get("x-test-mode"))
        try:
            return await lootbox_service.get_random_items(
                user_id=user_id, key_type=key_type, amount=amount, test_mode=test_mode
            )
        except InsufficientKeysError as e:
            raise CustomHTTPException(detail=str(e), status_code=HTTP_400_BAD_REQUEST) from e

    @litestar.post(
        path="/users/{user_id:int}/{key_type:str}/{reward_type:str}/{reward_name:str}",
        summary="Grant Reward",
        description="Grant a specific reward to a user.",
        status_code=HTTP_200_OK,
    )
    async def grant_reward_to_user(  # noqa: PLR0913
        self,
        lootbox_service: LootboxService,
        request: litestar.Request,
        user_id: int,
        key_type: LootboxKeyType,
        reward_type: str,
        reward_name: str,
    ) -> RewardTypeResponse:
        """Grant a specific reward to a user.

        Args:
            lootbox_service: Lootbox service.
            request: Request object.
            user_id: Target user ID.
            key_type: Key type.
            reward_type: Reward type.
            reward_name: Reward name.

        Returns:
            Reward response with duplicate flag and coin amount.

        Raises:
            CustomHTTPException: If user has insufficient keys.
        """
        test_mode = bool(request.headers.get("x-test-mode"))
        if test_mode:
            # In test mode, just grant the reward without key validation
            await lootbox_service.debug_grant_reward_no_key(
                user_id=user_id, key_type=key_type, reward_type=reward_type, reward_name=reward_name
            )
            # Return a minimal response
            return RewardTypeResponse(
                name=reward_name,
                key_type=key_type,
                rarity="common",
                type=reward_type,
                duplicate=False,
                coin_amount=0,
            )

        try:
            return await lootbox_service.grant_reward_to_user(
                user_id=user_id, reward_type=reward_type, key_type=key_type, reward_name=reward_name
            )
        except InsufficientKeysError as e:
            raise CustomHTTPException(detail=str(e), status_code=HTTP_400_BAD_REQUEST) from e

    @litestar.post(
        path="/users/{user_id:int}/keys/{key_type:str}",
        summary="Grant Key",
        description="Grant a key to a user.",
    )
    async def grant_key_to_user(
        self,
        lootbox_service: LootboxService,
        user_id: int,
        key_type: LootboxKeyType,
    ) -> Response:
        """Grant a key to a user.

        Args:
            lootbox_service: Lootbox service.
            user_id: Target user ID.
            key_type: Key type to grant.

        Returns:
            Response with 204 status.
        """
        await lootbox_service.grant_key_to_user(user_id=user_id, key_type=key_type)
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @litestar.post(
        path="/users/{user_id:int}/keys",
        summary="Grant Active Key",
        description="Grant the currently active key to a user.",
    )
    async def grant_active_key_to_user(
        self,
        lootbox_service: LootboxService,
        user_id: int,
    ) -> Response:
        """Grant the currently active key to a user.

        Args:
            lootbox_service: Lootbox service.
            user_id: Target user ID.

        Returns:
            Response with 204 status.
        """
        await lootbox_service.grant_active_key_to_user(user_id=user_id)
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @litestar.post(
        path="/users/debug/{user_id:int}/{key_type:str}/{reward_type:str}/{reward_name:str}",
        summary="DEBUG: Grant Reward Without Key",
        description="For debugging only. Grants a reward to a user without consuming a key.",
    )
    async def debug_grant_reward_no_key(
        self,
        lootbox_service: LootboxService,
        user_id: int,
        key_type: LootboxKeyType,
        reward_type: str,
        reward_name: str,
    ) -> Response:
        """DEBUG ONLY: Grant a reward to a user without consuming a key.

        Args:
            lootbox_service: Lootbox service.
            user_id: Target user ID.
            key_type: Key type.
            reward_type: Reward type.
            reward_name: Reward name or coin amount.

        Returns:
            Response with 204 status.
        """
        await lootbox_service.debug_grant_reward_no_key(
            user_id=user_id, key_type=key_type, reward_type=reward_type, reward_name=reward_name
        )
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @litestar.patch(
        path="/keys/{key_type:str}",
        summary="Set Active Key",
        description="Update the globally active key.",
    )
    async def update_active_key(
        self,
        lootbox_service: LootboxService,
        request: litestar.Request,
        key_type: LootboxKeyType,
    ) -> Response:
        """Update the globally active key.

        Args:
            lootbox_service: Lootbox service.
            request: Request object.
            key_type: Key type to set as active.

        Returns:
            Response with 204 status.
        """
        test_mode = bool(request.headers.get("x-test-mode"))
        if not test_mode:
            await lootbox_service.update_active_key(key_type=key_type)
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @litestar.get(
        path="/users/{user_id:int}/coins",
        summary="Get User Coins",
        description="Get the number of coins a user has.",
    )
    async def view_user_coins(
        self,
        lootbox_service: LootboxService,
        user_id: int,
    ) -> int:
        """Get the number of coins a user has.

        Args:
            lootbox_service: Lootbox service.
            user_id: Target user ID.

        Returns:
            Coin amount.
        """
        return await lootbox_service.view_user_coins(user_id=user_id)

    @litestar.post(
        path="/users/{user_id:int}/xp",
        summary="Grant XP to User",
        description="Add XP to a user and return their previous and new totals.",
        status_code=HTTP_200_OK,
    )
    async def grant_user_xp(
        self,
        lootbox_service: LootboxService,
        request: litestar.Request,
        user_id: int,
        data: Annotated[XpGrantRequest, Body(title="XP Grant Request")],
    ) -> XpGrantResponse:
        """Grant XP to a user.

        Args:
            lootbox_service: Lootbox service.
            request: Request object.
            user_id: Target user ID.
            data: XP grant request.

        Returns:
            XpGrantResponse with previous and new amounts.
        """
        # Service handles RabbitMQ publishing internally
        return await lootbox_service.grant_user_xp(request.headers, user_id, data)

    @litestar.get(
        path="/xp/tier",
        summary="Get XP Tier Change",
        description="Calculate tier change when XP is updated.",
    )
    async def get_xp_tier_change(
        self,
        lootbox_service: LootboxService,
        old_xp: int,
        new_xp: int,
    ) -> TierChangeResponse:
        """Calculate tier change when XP is updated.

        Args:
            lootbox_service: Lootbox service.
            old_xp: Previous XP amount.
            new_xp: New XP amount.

        Returns:
            TierChangeResponse with tier and prestige change details.
        """
        return await lootbox_service.get_xp_tier_change(old_xp=old_xp, new_xp=new_xp)

    @litestar.post(
        path="/xp/multiplier",
        summary="Change XP Multiplier",
        description="Change the XP multiplier, e.g. double XP weekends.",
    )
    async def update_xp_multiplier(
        self,
        lootbox_service: LootboxService,
        data: Annotated[XPMultiplierRequest, Body(title="XP Multiplier Request")],
    ) -> Response:
        """Change the XP multiplier.

        Args:
            lootbox_service: Lootbox service.
            data: XP multiplier request.

        Returns:
            Response with 204 status.
        """
        await lootbox_service.update_xp_multiplier(multiplier=float(data.value))
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @litestar.get(
        path="/xp/multiplier",
        summary="Get XP Multiplier",
        description="Get the XP multiplier, e.g. double XP weekends.",
    )
    async def get_xp_multiplier(
        self,
        lootbox_service: LootboxService,
    ) -> float:
        """Get the XP multiplier.

        Args:
            lootbox_service: Lootbox service.

        Returns:
            XP multiplier value.
        """
        return await lootbox_service.view_xp_multiplier()
