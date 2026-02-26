"""Service layer for lootbox domain business logic."""

from __future__ import annotations

import logging
import random

import msgspec
from asyncpg import Pool
from genjishimada_sdk.lootbox import (
    LootboxKeyType,
    LootboxKeyTypeResponse,
    RewardTypeResponse,
    UserLootboxKeyAmountResponse,
    UserRewardResponse,
)
from genjishimada_sdk.xp import TierChangeResponse, XpGrantEvent, XpGrantRequest, XpGrantResponse, XpSummaryResponse
from litestar.datastructures import State
from litestar.datastructures.headers import Headers

from repository.lootbox_repository import LootboxRepository
from services.base import BaseService
from services.exceptions.lootbox import InsufficientKeysError

log = logging.getLogger(__name__)

GACHA_WEIGHTS = {
    "legendary": 3,
    "epic": 5,
    "rare": 25,
    "common": 65,
}

DUPLICATE_COIN_VALUES = {
    "common": 100,
    "rare": 250,
    "epic": 500,
    "legendary": 1000,
}


class LootboxService(BaseService):
    """Service for lootbox domain business logic.

    Contains gacha logic, validation, duplicate detection,
    XP handling, and event generation.
    """

    def __init__(self, pool: Pool, state: State, lootbox_repo: LootboxRepository) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            lootbox_repo: Lootbox repository instance.
        """
        super().__init__(pool, state)
        self._lootbox_repo = lootbox_repo

    @staticmethod
    def _perform_gacha() -> str:
        """Perform weighted random selection for rarity.

        Uses GACHA_WEIGHTS to determine rarity.

        Returns:
            Selected rarity string (lowercase).
        """
        rarities = list(GACHA_WEIGHTS.keys())
        weights = list(GACHA_WEIGHTS.values())
        return random.choices(rarities, weights=weights, k=1)[0]

    async def view_all_rewards(
        self,
        reward_type: str | None = None,
        key_type: LootboxKeyType | None = None,
        rarity: str | None = None,
    ) -> list[RewardTypeResponse]:
        """Get all possible rewards with optional filters.

        Args:
            reward_type: Optional filter by reward type.
            key_type: Optional filter by key type.
            rarity: Optional filter by rarity.

        Returns:
            List of reward definitions.
        """
        rows = await self._lootbox_repo.fetch_all_rewards(
            reward_type=reward_type,
            key_type=key_type,
            rarity=rarity,
        )
        return msgspec.convert(rows, list[RewardTypeResponse])

    async def view_all_keys(
        self,
        key_type: LootboxKeyType | None = None,
    ) -> list[LootboxKeyTypeResponse]:
        """Get all possible key types with optional filter.

        Args:
            key_type: Optional filter by key type.

        Returns:
            List of key type definitions.
        """
        rows = await self._lootbox_repo.fetch_all_key_types(key_type=key_type)
        return msgspec.convert(rows, list[LootboxKeyTypeResponse])

    async def view_user_rewards(
        self,
        user_id: int,
        reward_type: str | None = None,
        key_type: LootboxKeyType | None = None,
        rarity: str | None = None,
    ) -> list[UserRewardResponse]:
        """Get all rewards earned by a user.

        Args:
            user_id: Target user ID.
            reward_type: Optional filter by reward type.
            key_type: Optional filter by key type.
            rarity: Optional filter by rarity.

        Returns:
            List of user rewards.
        """
        rows = await self._lootbox_repo.fetch_user_rewards(
            user_id=user_id,
            reward_type=reward_type,
            key_type=key_type,
            rarity=rarity,
        )
        return msgspec.convert(rows, list[UserRewardResponse])

    async def view_user_keys(
        self,
        user_id: int,
        key_type: LootboxKeyType | None = None,
    ) -> list[UserLootboxKeyAmountResponse]:
        """Get keys owned by a user grouped by key type.

        Args:
            user_id: Target user ID.
            key_type: Optional filter by key type.

        Returns:
            List of key counts by type.
        """
        rows = await self._lootbox_repo.fetch_user_keys(user_id=user_id, key_type=key_type)
        return msgspec.convert(rows, list[UserLootboxKeyAmountResponse])

    async def view_user_coins(self, user_id: int) -> int:
        """Get the number of coins a user has.

        Args:
            user_id: Target user ID.

        Returns:
            Coin amount.
        """
        return await self._lootbox_repo.fetch_user_coins(user_id)

    async def view_user_xp_summary(self, user_id: int) -> XpSummaryResponse | None:
        """Get a user's complete XP progression summary.

        Args:
            user_id: Target user ID.

        Returns:
            XP summary response, or None if user does not exist.
        """
        row = await self._lootbox_repo.fetch_user_xp_summary(user_id)
        if row is None:
            return None
        return msgspec.convert(row, XpSummaryResponse)

    async def view_xp_multiplier(self) -> float:
        """Get the current XP multiplier.

        Returns:
            XP multiplier value.
        """
        result = await self._lootbox_repo.fetch_xp_multiplier()
        return float(result)

    async def grant_key_to_user(
        self,
        user_id: int,
        key_type: LootboxKeyType,
    ) -> None:
        """Grant a key to a user.

        Args:
            user_id: Target user ID.
            key_type: Key type to grant.
        """
        await self._lootbox_repo.insert_user_key(user_id, key_type, conn=None)

    async def grant_active_key_to_user(
        self,
        user_id: int,
    ) -> None:
        """Grant the currently active key to a user.

        Args:
            user_id: Target user ID.
        """
        await self._lootbox_repo.insert_active_key(user_id, conn=None)

    async def grant_reward_to_user(
        self,
        user_id: int,
        reward_type: str,
        key_type: LootboxKeyType,
        reward_name: str,
    ) -> RewardTypeResponse:
        """Grant a specific reward to a user.

        Note: This method does NOT consume a key. Key consumption happens
        in get_random_items when the user previews rewards. This method
        only grants the chosen reward.

        Uses transaction to:
        1. Check if user already has the reward
        2. If duplicate, grant coins; else grant reward

        Args:
            user_id: Target user ID.
            reward_type: Reward type.
            key_type: Key type.
            reward_name: Reward name.

        Returns:
            Reward response with duplicate flag and coin amount.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            # Coin rewards are granted directly to the user's balance,
            # not tracked as collectible items in user_rewards.
            if reward_type == "coins":
                coin_amount = int(reward_name)
                await self._lootbox_repo.add_user_coins(user_id, coin_amount, conn=conn)  # type: ignore[arg-type]

                rewards = await self._lootbox_repo.fetch_all_rewards(
                    reward_type=reward_type,
                    key_type=key_type,
                    rarity=None,
                    conn=conn,  # type: ignore[arg-type]
                )
                matching = [r for r in rewards if r["name"] == reward_name]
                rarity_val = matching[0]["rarity"] if matching else "common"

                return RewardTypeResponse(
                    name=reward_name,
                    key_type=key_type,
                    rarity=rarity_val,
                    type=reward_type,
                    duplicate=False,
                    coin_amount=coin_amount,
                )

            rarity = await self._lootbox_repo.check_user_has_reward(
                user_id=user_id,
                reward_type=reward_type,
                key_type=key_type,
                reward_name=reward_name,
                conn=conn,  # type: ignore[arg-type]
            )

            if rarity:
                coin_amount = DUPLICATE_COIN_VALUES.get(rarity.lower(), 0)
                await self._lootbox_repo.add_user_coins(user_id, coin_amount, conn=conn)  # type: ignore[arg-type]

                return RewardTypeResponse(
                    name=reward_name,
                    key_type=key_type,
                    rarity=rarity,
                    type=reward_type,
                    duplicate=True,
                    coin_amount=coin_amount,
                )
            else:
                await self._lootbox_repo.insert_user_reward(
                    user_id=user_id,
                    reward_type=reward_type,
                    key_type=key_type,
                    reward_name=reward_name,
                    conn=conn,  # type: ignore[arg-type]
                )

                rewards = await self._lootbox_repo.fetch_all_rewards(
                    reward_type=reward_type,
                    key_type=key_type,
                    rarity=None,
                    conn=conn,  # type: ignore[arg-type]
                )
                matching = [r for r in rewards if r["name"] == reward_name]
                rarity_val = matching[0]["rarity"] if matching else "common"

                return RewardTypeResponse(
                    name=reward_name,
                    key_type=key_type,
                    rarity=rarity_val,
                    type=reward_type,
                    duplicate=False,
                    coin_amount=0,
                )

    async def get_random_items(
        self,
        user_id: int,
        key_type: LootboxKeyType,
        amount: int = 3,
        test_mode: bool = False,
    ) -> list[RewardTypeResponse]:
        """Get random rewards as a preview (no granting).

        Consumes one key and returns 3 random rewards for user to choose from.
        Call grant_reward_to_user to actually claim one of the rewards.

        Args:
            user_id: Target user ID.
            key_type: Key type to use.
            amount: Ignored, always generates 3 rewards.
            test_mode: If True, skip key consumption.

        Returns:
            List of 3 random rewards (preview only, not granted).

        Raises:
            InsufficientKeysError: If user has no keys to consume.
        """
        results: list[RewardTypeResponse] = []

        async with self._pool.acquire() as conn, conn.transaction():
            if not test_mode:
                key_deleted = await self._lootbox_repo.delete_oldest_user_key(
                    user_id,
                    key_type,
                    conn=conn,  # type: ignore[arg-type]
                )
                if not key_deleted:
                    raise InsufficientKeysError(key_type)

            for _ in range(3):
                rarity = self._perform_gacha()

                reward_row = await self._lootbox_repo.fetch_random_reward(
                    rarity=rarity,
                    key_type=key_type,
                    user_id=user_id,
                    conn=conn,  # type: ignore[arg-type]
                )

                if not reward_row:
                    log.warning(f"No reward found for rarity={rarity}, key_type={key_type}")
                    continue

                results.append(
                    RewardTypeResponse(
                        name=reward_row["name"],
                        key_type=key_type,
                        rarity=reward_row["rarity"],
                        type=reward_row["type"],
                        duplicate=reward_row.get("duplicate", False),
                        coin_amount=reward_row.get("coin_amount", 0),
                    )
                )

        return results

    async def grant_user_xp(
        self,
        headers: Headers,
        user_id: int,
        data: XpGrantRequest,
    ) -> XpGrantResponse:
        """Grant XP to a user and publish event to RabbitMQ.

        Args:
            headers: Request headers for idempotency.
            user_id: Target user ID.
            data: XP grant request.

        Returns:
            XP grant response.
        """
        multiplier = await self._lootbox_repo.fetch_xp_multiplier()

        result = await self._lootbox_repo.upsert_user_xp(
            user_id=user_id,
            xp_amount=data.amount,
            multiplier=float(multiplier),
        )

        response = XpGrantResponse(
            previous_amount=result["previous_amount"],
            new_amount=result["new_amount"],
        )

        event = XpGrantEvent(
            user_id=user_id,
            amount=data.amount,
            type=data.type,
            previous_amount=result["previous_amount"],
            new_amount=result["new_amount"],
            reason=data.reason,
        )

        await self.publish_message(
            routing_key="api.xp.grant",
            data=event,
            headers=headers,
        )

        return response

    async def update_xp_multiplier(self, multiplier: float) -> None:
        """Update the global XP multiplier.

        Args:
            multiplier: New multiplier value.
        """
        await self._lootbox_repo.update_xp_multiplier(multiplier)

    async def update_active_key(self, key_type: LootboxKeyType) -> None:
        """Update the globally active key.

        Args:
            key_type: Key type to set as active.
        """
        await self._lootbox_repo.update_active_key(key_type)

    async def get_xp_tier_change(self, old_xp: int, new_xp: int) -> TierChangeResponse:
        """Calculate tier change when XP is updated.

        Determines whether the user has ranked up, sub-ranked up,
        or achieved a prestige level change.

        Args:
            old_xp: Previous XP amount.
            new_xp: New XP amount.

        Returns:
            TierChangeResponse with tier and prestige change details.
        """
        result = await self._lootbox_repo.fetch_xp_tier_change(old_xp, new_xp)
        return msgspec.convert(result, TierChangeResponse)

    async def debug_grant_reward_no_key(
        self,
        user_id: int,
        key_type: LootboxKeyType,
        reward_type: str,
        reward_name: str,
    ) -> None:
        """DEBUG ONLY: Grant a reward to a user without consuming a key.

        Args:
            user_id: Target user ID.
            key_type: Key type.
            reward_type: Reward type.
            reward_name: Reward name or coin amount.
        """
        if reward_type != "coins":
            await self._lootbox_repo.insert_user_reward(
                user_id=user_id,
                reward_type=reward_type,
                key_type=key_type,
                reward_name=reward_name,
                conn=None,
            )
        else:
            coin_amount = int(reward_name)
            await self._lootbox_repo.add_user_coins(user_id, coin_amount, conn=None)


async def provide_lootbox_service(state: State) -> LootboxService:
    """Litestar DI provider for lootbox service.

    Args:
        state: Application state.

    Returns:
        LootboxService instance.
    """
    lootbox_repo = LootboxRepository(pool=state.db_pool)
    return LootboxService(pool=state.db_pool, state=state, lootbox_repo=lootbox_repo)
