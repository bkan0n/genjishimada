"""Service layer for store domain business logic."""

from __future__ import annotations

import datetime
import logging
import random
from typing import cast
from uuid import UUID

import msgspec
from asyncpg import Connection, Pool
from asyncpg.pool import PoolConnectionProxy
from genjishimada_sdk.lootbox import LootboxKeyType
from genjishimada_sdk.store import (
    AdminUpdateUserQuestRequest,
    AdminUpdateUserQuestResponse,
    ClaimQuestResponse,
    GenerateQuestRotationResponse,
    GenerateRotationResponse,
    ItemPurchaseResponse,
    KeyPriceInfo,
    KeyPricingResponse,
    KeyPurchaseResponse,
    PurchaseHistoryResponse,
    QuestConfigResponse,
    QuestHistoryItem,
    QuestHistoryResponse,
    QuestProgress,
    QuestResponse,
    QuestSummary,
    RotationItemResponse,
    RotationResponse,
    StoreConfigResponse,
    UpdateQuestConfigResponse,
    UserQuestsResponse,
)
from litestar.datastructures import State

from repository.lootbox_repository import LootboxRepository
from repository.store_repository import StoreRepository
from services.base import BaseService
from services.exceptions.store import (
    AlreadyOwnedError,
    InsufficientCoinsError,
    InvalidKeyTypeError,
    InvalidQuantityError,
    InvalidQuestPatchError,
    InvalidRotationItemCountError,
    ItemNotInRotationError,
    QuestAlreadyClaimedError,
    QuestNotCompletedError,
    QuestNotFoundError,
    RotationExpiredError,
)

log = logging.getLogger(__name__)

# Key pricing constants
ACTIVE_KEY_BASE_PRICE = 500
INACTIVE_KEY_BASE_PRICE = 1000
BULK_DISCOUNT_3X = 0.85  # 15% off
BULK_DISCOUNT_5X = 0.70  # 30% off

# Bulk purchase quantities
BULK_QUANTITY_3X = 3
BULK_QUANTITY_5X = 5

# Rotation item count limits
ROTATION_ITEM_MIN = 3
ROTATION_ITEM_MAX = 5


class StoreService(BaseService):
    """Service for store domain business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        store_repo: StoreRepository,
        lootbox_repo: LootboxRepository,
    ) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            store_repo: Store repository instance.
            lootbox_repo: Lootbox repository instance.
        """
        super().__init__(pool, state)
        self._store_repo = store_repo
        self._lootbox_repo = lootbox_repo

    async def _ensure_key_type_exists(
        self, key_type: str, *, conn: Connection | PoolConnectionProxy | None = None
    ) -> None:
        rows = await self._lootbox_repo.fetch_all_key_types(
            cast(LootboxKeyType, key_type),
            conn=conn,  # type: ignore[arg-type]
        )
        if not rows:
            raise InvalidKeyTypeError(key_type)

    @staticmethod
    def _validate_rotation_item_count(item_count: int) -> None:
        if item_count < ROTATION_ITEM_MIN or item_count > ROTATION_ITEM_MAX:
            raise InvalidRotationItemCountError(item_count)

    @staticmethod
    def _calculate_key_price(quantity: int, is_active: bool) -> int:
        """Calculate key price with bulk discount.

        Args:
            quantity: Number of keys (1, 3, or 5).
            is_active: Whether key type is active.

        Returns:
            Total price in coins.
        """
        base_price = ACTIVE_KEY_BASE_PRICE if is_active else INACTIVE_KEY_BASE_PRICE

        if quantity == 1:
            return base_price
        elif quantity == BULK_QUANTITY_3X:
            return int(base_price * BULK_QUANTITY_3X * BULK_DISCOUNT_3X)
        elif quantity == BULK_QUANTITY_5X:
            return int(base_price * BULK_QUANTITY_5X * BULK_DISCOUNT_5X)
        else:
            raise ValueError(f"Invalid quantity: {quantity}")

    async def get_config(self) -> StoreConfigResponse:
        """Get store configuration.

        Returns:
            Store configuration.
        """
        config = await self._store_repo.fetch_config()
        return msgspec.convert(config, StoreConfigResponse)

    async def get_current_rotation(
        self,
        user_id: int | None = None,
    ) -> RotationResponse:
        """Get current rotation items.

        Args:
            user_id: Optional user ID to check ownership.

        Returns:
            Current rotation with ownership flags.
        """
        items = await self._store_repo.fetch_current_rotation()

        if not items:
            return RotationResponse(
                rotation_id=UUID(int=0),
                available_until=datetime.datetime.now(datetime.timezone.utc),
                items=[],
            )

        rotation_id = items[0]["rotation_id"]
        available_until = items[0]["available_until"]

        # Check ownership for each item if user_id provided
        rotation_items = []
        for item in items:
            owned = False
            if user_id:
                rarity = await self._lootbox_repo.check_user_has_reward(
                    user_id=user_id,
                    reward_type=item["item_type"],
                    key_type=item["key_type"],
                    reward_name=item["item_name"],
                )
                owned = rarity is not None

            rotation_items.append(
                RotationItemResponse(
                    item_name=item["item_name"],
                    item_type=item["item_type"],
                    key_type=item["key_type"],
                    rarity=item["rarity"],
                    price=item["price"],
                    owned=owned,
                )
            )

        return RotationResponse(
            rotation_id=rotation_id,
            available_until=available_until,
            items=rotation_items,
        )

    async def get_key_pricing(self) -> list[KeyPricingResponse]:
        """Get key pricing for all key types.

        Returns:
            List of key pricing info.
        """
        config = await self._store_repo.fetch_config()
        active_key_type = config["active_key_type"]

        # Get all key types
        key_types = await self._lootbox_repo.fetch_all_key_types()

        pricing_list = []
        for key_type_row in key_types:
            key_type = key_type_row["name"]
            is_active = key_type == active_key_type

            prices = [
                KeyPriceInfo(
                    quantity=1,
                    price=self._calculate_key_price(1, is_active),
                    discount_percent=0,
                ),
                KeyPriceInfo(
                    quantity=3,
                    price=self._calculate_key_price(3, is_active),
                    discount_percent=15,
                ),
                KeyPriceInfo(
                    quantity=5,
                    price=self._calculate_key_price(5, is_active),
                    discount_percent=30,
                ),
            ]

            pricing_list.append(
                KeyPricingResponse(
                    key_type=key_type,
                    is_active=is_active,
                    prices=prices,
                )
            )

        return pricing_list

    async def purchase_keys(
        self,
        user_id: int,
        key_type: str,
        quantity: int,
    ) -> KeyPurchaseResponse:
        """Purchase lootbox keys with coins.

        Args:
            user_id: User making purchase.
            key_type: Type of key to purchase.
            quantity: Number of keys (must be 1, 3, or 5).

        Returns:
            Purchase response with remaining balance.

        Raises:
            InvalidQuantityError: If quantity is not 1, 3, or 5.
            InvalidKeyTypeError: If key type does not exist.
            InsufficientCoinsError: If user doesn't have enough coins.
        """
        if quantity not in [1, 3, 5]:
            raise InvalidQuantityError(quantity)

        config = await self._store_repo.fetch_config()
        is_active = key_type == config["active_key_type"]

        price = self._calculate_key_price(quantity, is_active)

        async with self._pool.acquire() as conn, conn.transaction():
            await self._ensure_key_type_exists(key_type, conn=conn)

            new_balance = await self._lootbox_repo.deduct_user_coins(
                user_id,
                price,
                conn=conn,  # type: ignore[arg-type]
            )
            if new_balance is None:
                user_coins = await self._lootbox_repo.fetch_user_coins(
                    user_id,
                    conn=conn,  # type: ignore[arg-type]
                )
                raise InsufficientCoinsError(user_coins, price)

            for _ in range(quantity):
                await self._lootbox_repo.insert_user_key(user_id, key_type, conn=conn)  # type: ignore[arg-type]

            await self._store_repo.insert_purchase(
                user_id=user_id,
                purchase_type="key",
                key_type=key_type,
                quantity=quantity,
                price_paid=price,
                conn=conn,  # type: ignore[arg-type]
            )

            remaining_coins = new_balance

        log.info(
            "User %s purchased %s %s key(s) for %s coins",
            user_id,
            quantity,
            key_type,
            price,
        )

        return KeyPurchaseResponse(
            success=True,
            keys_purchased=quantity,
            price_paid=price,
            remaining_coins=remaining_coins,
        )

    async def purchase_item(
        self,
        user_id: int,
        item_name: str,
        item_type: str,
        key_type: str,
    ) -> ItemPurchaseResponse:
        """Purchase an item from current rotation.

        Args:
            user_id: User making purchase.
            item_name: Name of item to purchase.
            item_type: Type of item.
            key_type: Associated key type.

        Returns:
            Purchase response with remaining balance.

        Raises:
            ItemNotInRotationError: If item not in current rotation.
            RotationExpiredError: If rotation has expired.
            AlreadyOwnedError: If user already owns the item.
            InsufficientCoinsError: If user doesn't have enough coins.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            rotation_item = await self._store_repo.fetch_rotation_item(
                item_name,
                item_type,
                key_type,
                conn=conn,  # type: ignore[arg-type]
            )
            if not rotation_item:
                raise ItemNotInRotationError(item_name)

            if rotation_item["available_until"] < datetime.datetime.now(datetime.timezone.utc):
                raise RotationExpiredError()

            already_owned = await self._lootbox_repo.check_user_has_reward(
                user_id,
                item_type,
                cast(LootboxKeyType, key_type),
                item_name,
                conn=conn,  # type: ignore[arg-type]
            )
            if already_owned:
                raise AlreadyOwnedError(item_name)

            price = rotation_item["price"]

            new_balance = await self._lootbox_repo.deduct_user_coins(
                user_id,
                price,
                conn=conn,  # type: ignore[arg-type]
            )
            if new_balance is None:
                user_coins = await self._lootbox_repo.fetch_user_coins(
                    user_id,
                    conn=conn,  # type: ignore[arg-type]
                )
                raise InsufficientCoinsError(user_coins, price)

            await self._lootbox_repo.insert_user_reward(
                user_id,
                item_type,
                cast(LootboxKeyType, key_type),
                item_name,
                conn=conn,  # type: ignore[arg-type]
            )

            await self._store_repo.insert_purchase(
                user_id=user_id,
                purchase_type="item",
                item_name=item_name,
                item_type=item_type,
                key_type=key_type,
                quantity=1,
                price_paid=price,
                rotation_id=rotation_item["rotation_id"],
                conn=conn,  # type: ignore[arg-type]
            )

            remaining_coins = new_balance

        log.info(
            "User %s purchased item '%s' (%s, %s) for %s coins",
            user_id,
            item_name,
            item_type,
            key_type,
            price,
        )

        return ItemPurchaseResponse(
            success=True,
            item_name=item_name,
            item_type=item_type,
            price_paid=price,
            remaining_coins=remaining_coins,
        )

    async def get_user_purchases(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> PurchaseHistoryResponse:
        """Get user's purchase history.

        Args:
            user_id: User ID.
            limit: Max results.
            offset: Result offset.

        Returns:
            Purchase history response.
        """
        total, purchases = await self._store_repo.fetch_user_purchases(user_id, limit, offset)
        return msgspec.convert({"total": total, "purchases": purchases}, PurchaseHistoryResponse)

    async def get_user_quests(self, user_id: int) -> UserQuestsResponse:
        """Get active quests for a user with progress and summary."""
        rotation_id = await self.ensure_user_quests_for_rotation(user_id)
        rotation = await self._store_repo.get_active_rotation()
        available_until = rotation.get("available_until")

        quest_rows = await self._store_repo.get_active_user_quests(user_id)

        quests: list[QuestResponse] = []
        summary = QuestSummary(
            total_quests=0,
            completed=0,
            claimed=0,
            potential_coins=0,
            potential_xp=0,
            earned_coins=0,
            earned_xp=0,
        )

        for row in quest_rows:
            quest_data = row.get("quest_data") or {}
            progress_raw = row.get("progress") or {}

            completed = row.get("completed_at") is not None
            claimed = row.get("claimed_at") is not None

            # Compute percentage before struct conversion
            percentage = 0
            target_raw = progress_raw.get("target")
            target_val = float(target_raw) if isinstance(target_raw, (int, float)) else 0.0
            if target_val:
                current_raw = progress_raw.get("current")
                current_val = float(current_raw) if isinstance(current_raw, (int, float)) else 0.0
                percentage = min(100, int((current_val / target_val) * 100))
            elif completed:
                percentage = 100
            progress_raw["percentage"] = percentage

            # Coerce non-numeric progress fields to None for struct conversion
            # (e.g., complete_map quests store target as "complete" string)
            for field in ("current", "target"):
                val = progress_raw.get(field)
                if not isinstance(val, (int, float, type(None))):
                    progress_raw[field] = None

            # Merge requirement fields that belong in progress but may not have been
            # copied during initial seeding (backfill for existing rows)
            requirements = quest_data.get("requirements") or {}
            for field in ("rival_user_id", "rival_time", "medal_type"):
                if requirements.get(field) is not None:
                    progress_raw.setdefault(field, requirements[field])

            progress = msgspec.convert(progress_raw, QuestProgress)

            coin_reward = quest_data.get("coin_reward") or 0
            xp_reward = quest_data.get("xp_reward") or 0

            quests.append(
                QuestResponse(
                    progress_id=row["progress_id"],
                    quest_id=row.get("quest_id"),
                    name=cast(str, quest_data.get("name", "")),
                    description=cast(str, quest_data.get("description", "")),
                    difficulty=cast(str, quest_data.get("difficulty", "")),
                    coin_reward=coin_reward,
                    xp_reward=xp_reward,
                    progress=progress,
                    completed=completed,
                    claimed=claimed,
                    bounty_type=cast("str | None", quest_data.get("bounty_type")),
                )
            )

            summary.total_quests += 1
            summary.potential_coins += coin_reward
            summary.potential_xp += xp_reward
            if completed:
                summary.completed += 1
            if claimed:
                summary.claimed += 1
            summary.earned_coins += row.get("coins_rewarded") or 0
            summary.earned_xp += row.get("xp_rewarded") or 0

        return UserQuestsResponse(
            rotation_id=rotation_id,
            available_until=available_until,
            quests=quests,
            summary=summary,
        )

    async def get_user_quest_history(self, user_id: int, limit: int = 20, offset: int = 0) -> QuestHistoryResponse:
        """Get completed quest history for a user."""
        total, rows = await self._store_repo.fetch_quest_history(user_id, limit, offset)
        quests: list[QuestHistoryItem] = []
        for row in rows:
            quest_data = row.get("quest_data") or {}
            quests.append(
                QuestHistoryItem(
                    progress_id=row["progress_id"],
                    quest_id=row.get("quest_id"),
                    name=cast("str | None", quest_data.get("name")),
                    description=cast("str | None", quest_data.get("description")),
                    difficulty=cast("str | None", quest_data.get("difficulty")),
                    coin_reward=quest_data.get("coin_reward") or 0,
                    xp_reward=quest_data.get("xp_reward") or 0,
                    completed_at=row.get("completed_at"),
                    claimed_at=row.get("claimed_at"),
                    coins_rewarded=row.get("coins_rewarded") or 0,
                    xp_rewarded=row.get("xp_rewarded") or 0,
                    rotation_id=row.get("rotation_id"),
                    bounty_type=cast("str | None", quest_data.get("bounty_type")),
                )
            )
        return QuestHistoryResponse(total=total or 0, quests=quests)

    async def generate_rotation(self, item_count: int = 5) -> GenerateRotationResponse:
        """Generate a new store rotation.

        Args:
            item_count: Number of items to generate.

        Returns:
            Rotation generation result.
        """
        self._validate_rotation_item_count(item_count)
        result = await self._store_repo.generate_rotation(item_count)
        return msgspec.convert(result, GenerateRotationResponse)

    async def ensure_user_quests_for_rotation(self, user_id: int) -> UUID:
        """Ensure quest rows exist for this user and current rotation."""
        async with self._pool.acquire() as conn:
            await conn.execute("SELECT store.check_and_generate_quest_rotation()")
            rotation = await self._store_repo.get_active_rotation(conn=conn)  # type: ignore[arg-type]
            rotation_id = rotation.get("rotation_id")
            if not rotation_id:
                raise RuntimeError("Quest rotation not available.")

            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))",
                    f"quest_provision:{user_id}:{rotation_id}",
                )

                if await self._store_repo.has_progress_rows(
                    user_id,
                    rotation_id,
                    conn=conn,  # type: ignore[arg-type]
                ):
                    return rotation_id

                global_quests = await self._store_repo.get_global_quests(
                    rotation_id,
                    conn=conn,  # type: ignore[arg-type]
                )
                await self._store_repo.seed_global_progress(
                    user_id,
                    rotation_id,
                    global_quests,
                    conn=conn,  # type: ignore[arg-type]
                )

                existing_bounty = await self._store_repo.get_bounty_for_user(
                    rotation_id,
                    user_id,
                    conn=conn,  # type: ignore[arg-type]
                )
                if not existing_bounty:
                    bounty = await self.generate_bounty_for_user(user_id, rotation_id)
                    await self._store_repo.insert_bounty(
                        rotation_id,
                        user_id,
                        bounty["quest_data"],
                        conn=conn,  # type: ignore[arg-type]
                    )
                    await self._store_repo.seed_bounty_progress(
                        user_id,
                        rotation_id,
                        bounty["quest_data"],
                        conn=conn,  # type: ignore[arg-type]
                    )

        return rotation_id

    async def generate_bounty_for_user(self, user_id: int, rotation_id: UUID) -> dict:
        """Generate personalized bounty for a user."""
        bounty_type = random.choices(
            ["personal_improvement", "rival_challenge", "gap_filling"],
            weights=[0.33, 0.33, 0.33],
        )[0]

        if bounty_type == "personal_improvement":
            return await self._generate_personal_improvement_bounty(user_id, rotation_id)
        if bounty_type == "rival_challenge":
            return await self._generate_rival_challenge_bounty(user_id, rotation_id)
        return await self._generate_gap_filling_bounty(user_id, rotation_id)

    async def _generate_personal_improvement_bounty(self, user_id: int, rotation_id: UUID) -> dict:
        """Generate personal improvement bounty: beat your own PB or upgrade medal."""
        completions = await self._store_repo.get_user_completions(user_id)
        if not completions:
            return await self._generate_gap_filling_bounty(user_id, rotation_id)

        completion = random.choice(completions)
        medal_thresholds = await self._store_repo.get_medal_thresholds(completion["map_id"])
        percentile_target = await self._store_repo.get_percentile_target_time(
            completion["map_id"],
            0.6,
        )
        if percentile_target is not None:
            percentile_target = float(percentile_target)

        medal_target = None
        target_medal = None
        if medal_thresholds:
            for medal_name in ("gold", "silver", "bronze"):
                threshold = medal_thresholds.get(medal_name)
                if threshold and completion["time"] > float(threshold):
                    medal_target = float(threshold)
                    target_medal = medal_name
                    break

        if medal_target and percentile_target:
            target_time = max(medal_target, percentile_target)
            target_type = "medal_threshold" if target_time == medal_target else "percentile"
        elif medal_target:
            target_time = medal_target
            target_type = "medal_threshold"
        elif percentile_target:
            target_time = percentile_target
            target_type = "percentile"
        else:
            target_time = completion["time"] * 0.9
            target_type = "personal_best"

        requirements: dict = {
            "type": "beat_time",
            "map_id": completion["map_id"],
            "target_time": target_time,
            "target_type": target_type,
        }
        if target_type == "medal_threshold":
            requirements["medal_type"] = target_medal

        return {
            "user_id": user_id,
            "rotation_id": rotation_id,
            "quest_data": {
                "name": "Beat Your Best",
                "description": f"Improve your time on {completion['code']}",
                "difficulty": "bounty",
                "coin_reward": 300,
                "xp_reward": 50,
                "bounty_type": "personal_improvement",
                "requirements": requirements,
            },
        }

    async def _generate_rival_challenge_bounty(self, user_id: int, rotation_id: UUID) -> dict:
        """Generate rival challenge bounty: beat another player's time."""
        skill_rank = await self._store_repo.get_user_skill_rank(user_id)
        rivals = await self._store_repo.find_rivals(user_id, skill_rank)
        if not rivals:
            return await self._generate_personal_improvement_bounty(user_id, rotation_id)

        rival = random.choice(rivals)
        target_map = await self._store_repo.find_beatable_rival_map(user_id, rival["user_id"])
        if not target_map:
            return await self._generate_personal_improvement_bounty(user_id, rotation_id)

        rival_time = float(target_map["rival_time"])

        return {
            "user_id": user_id,
            "rotation_id": rotation_id,
            "quest_data": {
                "name": "Rival Challenge",
                "description": f"Beat {rival['username']}'s time on {target_map['code']}",
                "difficulty": "bounty",
                "coin_reward": 300,
                "xp_reward": 50,
                "bounty_type": "rival_challenge",
                "requirements": {
                    "type": "beat_rival",
                    "map_id": target_map["map_id"],
                    "rival_user_id": rival["user_id"],
                    "rival_time": rival_time,
                    "target_time": rival_time,
                },
            },
        }

    async def _generate_gap_filling_bounty(self, user_id: int, rotation_id: UUID) -> dict:
        """Generate gap filling bounty: complete an unplayed map."""
        uncompleted = await self._store_repo.get_uncompleted_maps(user_id)
        if not uncompleted:
            return {
                "user_id": user_id,
                "rotation_id": rotation_id,
                "quest_data": {
                    "name": "Explore New Territory",
                    "description": "Complete a new map",
                    "difficulty": "bounty",
                    "coin_reward": 300,
                    "xp_reward": 50,
                    "bounty_type": "gap_filling",
                    "requirements": {
                        "type": "complete_map",
                        "map_id": 0,
                        "target": "complete",
                    },
                },
            }

        target_map = random.choice(uncompleted)
        return {
            "user_id": user_id,
            "rotation_id": rotation_id,
            "quest_data": {
                "name": "Explore New Territory",
                "description": f"Complete {target_map['code']}",
                "difficulty": "bounty",
                "coin_reward": 300,
                "xp_reward": 50,
                "bounty_type": "gap_filling",
                "requirements": {
                    "type": "complete_map",
                    "map_id": target_map["map_id"],
                    "target": "complete",
                },
            },
        }

    def _match_complete_maps(self, requirements: dict, event_type: str, event_data: dict) -> bool:
        if event_type != "completion":
            return False
        req_difficulty = requirements.get("difficulty")
        if req_difficulty and req_difficulty != "any":
            event_difficulty = (event_data.get("difficulty") or "").lower()
            if event_difficulty != str(req_difficulty).lower():
                return False
        req_category = requirements.get("category")
        if req_category:
            event_category = (event_data.get("category") or "").lower()
            if event_category != str(req_category).lower():
                return False
        return True

    def _match_earn_medals(self, requirements: dict, event_type: str, event_data: dict) -> bool:
        if event_type != "completion":
            return False
        event_medal = event_data.get("medal")
        if not event_medal:
            return False
        req_medal = requirements.get("medal_type")
        if req_medal and str(req_medal).lower() != "any":
            return str(event_medal).lower() == str(req_medal).lower()
        return True

    def _match_complete_difficulty_range(self, requirements: dict, event_type: str, event_data: dict) -> bool:
        if event_type != "completion":
            return False
        event_difficulty = (event_data.get("difficulty") or "").lower()
        req_difficulty = (requirements.get("difficulty") or "").lower()
        return event_difficulty == req_difficulty

    def _match_map_specific(self, requirements: dict, event_type: str, event_data: dict) -> bool:
        if event_type != "completion":
            return False
        return event_data.get("map_id") == requirements.get("map_id")

    def _event_matches_quest(self, requirements: dict, event_type: str, event_data: dict) -> bool:
        req_type = requirements.get("type")
        if not isinstance(req_type, str):
            return False
        handlers = {
            "complete_maps": self._match_complete_maps,
            "earn_medals": self._match_earn_medals,
            "complete_difficulty_range": self._match_complete_difficulty_range,
            "beat_time": self._match_map_specific,
            "beat_rival": self._match_map_specific,
            "complete_map": self._match_map_specific,
        }
        handler = handlers.get(req_type)
        if not handler:
            return False
        return handler(requirements, event_type, event_data)

    def _calculate_new_progress(self, progress: dict, requirements: dict, event_data: dict) -> dict:
        current_progress = dict(progress)
        req_type = requirements.get("type")
        if not isinstance(req_type, str):
            return current_progress

        if req_type == "complete_maps":
            map_id = event_data.get("map_id")
            completed = set(current_progress.get("completed_map_ids", []))
            if map_id in completed:
                return current_progress
            completed.add(map_id)
            current_progress["completed_map_ids"] = list(completed)
            current_progress["current"] = current_progress.get("current", 0) + 1
            details = current_progress.get("details") or {}
            difficulty = (event_data.get("difficulty") or "").lower()
            details[difficulty] = details.get(difficulty, 0) + 1
            current_progress["details"] = details

        elif req_type == "earn_medals":
            map_id = event_data.get("map_id")
            counted = set(current_progress.get("counted_map_ids", []))
            if map_id in counted:
                return current_progress
            counted.add(map_id)
            current_progress["counted_map_ids"] = list(counted)
            current_progress["current"] = current_progress.get("current", 0) + 1
            medals = current_progress.get("medals") or []
            medals.append({"map_id": map_id, "medal_type": event_data.get("medal")})
            current_progress["medals"] = medals

        elif req_type == "complete_difficulty_range":
            map_id = event_data.get("map_id")
            completed = set(current_progress.get("completed_map_ids", []))
            if map_id in completed:
                return current_progress
            completed.add(map_id)
            current_progress["completed_map_ids"] = list(completed)
            current_progress["current"] = current_progress.get("current", 0) + 1

        elif req_type in {"beat_time", "beat_rival"}:
            time_value = event_data.get("time")
            if time_value is None:
                return current_progress
            new_time = float(time_value)
            current_progress["last_attempt"] = new_time
            best_attempt = current_progress.get("best_attempt")
            best_value = float(best_attempt) if best_attempt is not None else float("inf")
            current_progress["best_attempt"] = min(best_value, new_time)

        elif req_type == "complete_map":
            current_progress["completed"] = True
            if event_data.get("medal"):
                current_progress["medal_earned"] = event_data.get("medal")

        return current_progress

    def _revert_complete_maps(
        self,
        current_progress: dict,
        event_data: dict,
        has_remaining_completion: bool,
    ) -> dict:
        map_id = event_data.get("map_id")
        if map_id is None:
            return current_progress
        completed = set(current_progress.get("completed_map_ids", []))
        if map_id not in completed or has_remaining_completion:
            return current_progress
        completed.remove(map_id)
        current_progress["completed_map_ids"] = list(completed)
        current_progress["current"] = max(0, current_progress.get("current", 0) - 1)
        details = current_progress.get("details") or {}
        difficulty = (event_data.get("difficulty") or "").lower()
        if difficulty:
            details[difficulty] = max(0, details.get(difficulty, 0) - 1)
            if details[difficulty] <= 0:
                details.pop(difficulty, None)
        if details:
            current_progress["details"] = details
        else:
            current_progress.pop("details", None)
        return current_progress

    def _revert_earn_medals(
        self,
        current_progress: dict,
        requirements: dict,
        event_data: dict,
        remaining_medals: list[str],
    ) -> dict:
        map_id = event_data.get("map_id")
        if map_id is None:
            return current_progress
        counted = set(current_progress.get("counted_map_ids", []))
        if map_id not in counted:
            return current_progress
        req_medal = requirements.get("medal_type")
        if req_medal and str(req_medal).lower() != "any":
            still_counts = any(str(m).lower() == str(req_medal).lower() for m in remaining_medals)
        else:
            still_counts = len(remaining_medals) > 0
        if still_counts:
            return current_progress
        counted.remove(map_id)
        current_progress["counted_map_ids"] = list(counted)
        current_progress["current"] = max(0, current_progress.get("current", 0) - 1)
        medals = current_progress.get("medals") or []
        medals = [m for m in medals if m.get("map_id") != map_id]
        if medals:
            current_progress["medals"] = medals
        else:
            current_progress.pop("medals", None)
        return current_progress

    def _revert_complete_difficulty_range(
        self,
        current_progress: dict,
        event_data: dict,
        has_remaining_completion: bool,
    ) -> dict:
        map_id = event_data.get("map_id")
        if map_id is None:
            return current_progress
        completed = set(current_progress.get("completed_map_ids", []))
        if map_id not in completed or has_remaining_completion:
            return current_progress
        completed.remove(map_id)
        current_progress["completed_map_ids"] = list(completed)
        current_progress["current"] = max(0, current_progress.get("current", 0) - 1)
        return current_progress

    def _revert_best_time(self, current_progress: dict, remaining_times: list[float]) -> dict:
        best_time = min(remaining_times) if remaining_times else None
        if best_time is None:
            current_progress.pop("best_attempt", None)
            current_progress.pop("last_attempt", None)
        else:
            current_progress["best_attempt"] = best_time
            current_progress["last_attempt"] = best_time
        return current_progress

    def _revert_complete_map(self, current_progress: dict, has_remaining_completion: bool) -> dict:
        if has_remaining_completion:
            return current_progress
        current_progress["completed"] = False
        current_progress.pop("medal_earned", None)
        return current_progress

    def _calculate_reverted_progress(
        self,
        progress: dict,
        requirements: dict,
        event_data: dict,
        remaining_times: list[float],
        remaining_medals: list[str],
    ) -> dict:
        current_progress = dict(progress)
        has_remaining_completion = len(remaining_times) > 0
        req_type = requirements.get("type")
        if not isinstance(req_type, str):
            return current_progress
        handlers = {
            "complete_maps": lambda: self._revert_complete_maps(current_progress, event_data, has_remaining_completion),
            "earn_medals": lambda: self._revert_earn_medals(
                current_progress, requirements, event_data, remaining_medals
            ),
            "complete_difficulty_range": lambda: self._revert_complete_difficulty_range(
                current_progress, event_data, has_remaining_completion
            ),
            "beat_time": lambda: self._revert_best_time(current_progress, remaining_times),
            "beat_rival": lambda: self._revert_best_time(current_progress, remaining_times),
            "complete_map": lambda: self._revert_complete_map(current_progress, has_remaining_completion),
        }
        handler = handlers.get(req_type)
        if not handler:
            return current_progress
        return handler()

    def _is_complete_time_target(self, progress: dict, requirements: dict) -> bool:
        target_time = requirements.get("target_time")
        if target_time is None:
            return False
        best_attempt = progress.get("best_attempt")
        best_value = float(best_attempt) if best_attempt is not None else float("inf")
        return best_value < float(target_time)

    def _is_quest_complete(self, progress: dict, requirements: dict) -> bool:
        req_type = requirements.get("type")
        if not isinstance(req_type, str):
            return False
        handlers = {
            "complete_maps": lambda: progress.get("current", 0) >= requirements.get("count", 0),
            "earn_medals": lambda: progress.get("current", 0) >= requirements.get("count", 0),
            "complete_difficulty_range": lambda: progress.get("current", 0) >= requirements.get("min_count", 0),
            "beat_time": lambda: self._is_complete_time_target(progress, requirements),
            "beat_rival": lambda: self._is_complete_time_target(progress, requirements),
            "complete_map": lambda: progress.get("completed", False) is True,
        }
        handler = handlers.get(req_type)
        if not handler:
            return False
        return handler()

    async def update_quest_progress(
        self,
        *,
        user_id: int,
        event_type: str,
        event_data: dict,
    ) -> list[dict]:
        """Update quest progress and return newly completed quests."""
        await self.ensure_user_quests_for_rotation(user_id)

        completed_quests: list[dict] = []
        async with self._pool.acquire() as conn, conn.transaction():
            quests = await self._store_repo.get_active_user_quests(
                user_id,
                conn=conn,  # type: ignore[arg-type]
            )

            for quest in quests:
                if quest.get("completed_at"):
                    continue

                quest_data = quest.get("quest_data") or {}
                progress = quest.get("progress") or {}
                requirements = quest_data.get("requirements") or {}

                if not self._event_matches_quest(requirements, event_type, event_data):
                    continue

                new_progress = self._calculate_new_progress(progress, requirements, event_data)
                await self._store_repo.update_quest_progress(
                    quest["progress_id"],
                    new_progress,
                    conn=conn,  # type: ignore[arg-type]
                )

                if self._is_quest_complete(new_progress, requirements):
                    await self._store_repo.mark_quest_complete(
                        quest["progress_id"],
                        conn=conn,  # type: ignore[arg-type]
                    )
                    completed_quests.append({"progress_id": quest["progress_id"], **quest_data})

        return completed_quests

    async def revert_quest_progress(
        self,
        *,
        user_id: int,
        event_type: str,
        event_data: dict,
        remaining_times: list[float],
        remaining_medals: list[str],
    ) -> None:
        """Revert quest progress and un-complete quests when a completion is unverified."""
        await self.ensure_user_quests_for_rotation(user_id)

        async with self._pool.acquire() as conn, conn.transaction():
            quests = await self._store_repo.get_active_user_quests(
                user_id,
                conn=conn,  # type: ignore[arg-type]
            )

            for quest in quests:
                quest_data = quest.get("quest_data") or {}
                progress = quest.get("progress") or {}
                requirements = quest_data.get("requirements") or {}

                if quest.get("completed_at") is not None:
                    continue

                if not self._event_matches_quest(requirements, event_type, event_data):
                    continue

                new_progress = self._calculate_reverted_progress(
                    progress,
                    requirements,
                    event_data,
                    remaining_times,
                    remaining_medals,
                )

                if new_progress == progress:
                    continue

                await self._store_repo.update_quest_progress(
                    quest["progress_id"],
                    new_progress,
                    conn=conn,  # type: ignore[arg-type]
                )

    async def claim_quest(self, *, user_id: int, progress_id: int) -> ClaimQuestResponse:
        """Claim a completed quest and grant rewards."""
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE store.user_quest_progress
                SET claimed_at = now(),
                    coins_rewarded = (quest_data->>'coin_reward')::int,
                    xp_rewarded = (quest_data->>'xp_reward')::int
                WHERE id = $1
                  AND user_id = $2
                  AND completed_at IS NOT NULL
                  AND claimed_at IS NULL
                RETURNING quest_data, coins_rewarded, xp_rewarded
                """,
                progress_id,
                user_id,
            )

            if not row:
                status = await conn.fetchrow(
                    """
                    SELECT completed_at, claimed_at
                    FROM store.user_quest_progress
                    WHERE id = $1 AND user_id = $2
                    """,
                    progress_id,
                    user_id,
                )
                if not status:
                    raise QuestNotFoundError(progress_id)
                if status["claimed_at"] is not None:
                    raise QuestAlreadyClaimedError(progress_id)
                raise QuestNotCompletedError(progress_id)

            quest_data = row["quest_data"] or {}
            coin_reward = row["coins_rewarded"] or 0
            xp_reward = row["xp_rewarded"] or 0

            new_coins = await conn.fetchval(
                """
                UPDATE core.users
                SET coins = coins + $2
                WHERE id = $1
                RETURNING coins
                """,
                user_id,
                coin_reward,
            )

            new_xp = await conn.fetchval(
                """
                INSERT INTO lootbox.xp (user_id, amount)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE
                    SET amount = lootbox.xp.amount + EXCLUDED.amount
                RETURNING amount
                """,
                user_id,
                xp_reward,
            )

        return ClaimQuestResponse(
            success=True,
            quest_name=cast("str | None", quest_data.get("name")),
            coins_earned=coin_reward,
            xp_earned=xp_reward,
            new_coin_balance=new_coins,
            new_xp=new_xp,
        )

    @staticmethod
    def _merge_quest_data_patch(existing: dict, patch: msgspec.Struct) -> dict:
        """Merge a PatchQuestData into existing quest_data dict."""
        merged = dict(existing)
        patch_fields = {k: v for k, v in msgspec.structs.asdict(patch).items() if v is not msgspec.UNSET}

        # Handle nested requirements merge
        req_patch = patch_fields.pop("requirements", None)
        if isinstance(req_patch, dict):
            filtered_req = {k: v for k, v in req_patch.items() if v is not msgspec.UNSET}
            existing_req = merged.get("requirements") or {}
            existing_req.update(filtered_req)
            merged["requirements"] = existing_req

        merged.update(patch_fields)
        return merged

    @staticmethod
    def _auto_patch_progress_for_completion(existing_progress: dict, requirements: dict) -> dict:
        """Auto-patch progress fields when marking a quest as complete."""
        progress = dict(existing_progress)
        req_type = requirements.get("type")

        if req_type in ("complete_maps", "earn_medals"):
            progress["current"] = requirements.get("count", 0)
        elif req_type == "complete_difficulty_range":
            progress["current"] = requirements.get("min_count", 0)
        elif req_type == "complete_map":
            progress["completed"] = True
        elif req_type == "beat_time":
            target_time = requirements.get("target_time")
            if target_time is not None:
                progress["best_attempt"] = float(target_time) - 0.01
        elif req_type == "beat_rival":
            rival_time = requirements.get("rival_time")
            if rival_time is not None:
                progress["best_attempt"] = float(rival_time) - 0.01

        return progress

    async def admin_update_user_quest(
        self,
        user_id: int,
        progress_id: int,
        data: AdminUpdateUserQuestRequest,
    ) -> AdminUpdateUserQuestResponse:
        """Admin-update a user's quest progress, data, or completion status.

        Args:
            user_id: Target user ID.
            progress_id: Quest progress row ID.
            data: Patch request with optional fields.

        Returns:
            Success response.

        Raises:
            InvalidQuestPatchError: If all fields are UNSET.
            QuestNotFoundError: If progress row not found.
        """
        if not any(v is not msgspec.UNSET for v in msgspec.structs.asdict(data).values()):
            raise InvalidQuestPatchError()

        existing = await self._store_repo.get_user_quest_progress(user_id, progress_id)
        if not existing:
            raise QuestNotFoundError(progress_id)

        existing_quest_data = existing.get("quest_data") or {}
        existing_progress = existing.get("progress") or {}

        quest_data_dict = (
            self._merge_quest_data_patch(existing_quest_data, data.quest_data)
            if data.quest_data is not msgspec.UNSET
            else None
        )

        effective_quest_data = quest_data_dict if quest_data_dict is not None else existing_quest_data

        completed_at: object = msgspec.UNSET
        auto_patched: dict | None = None
        if data.completed is not msgspec.UNSET:
            if data.completed:
                completed_at = datetime.datetime.now(datetime.timezone.utc)
                requirements = effective_quest_data.get("requirements") or {}
                auto_patched = self._auto_patch_progress_for_completion(existing_progress, requirements)
            else:
                completed_at = None

        if data.progress is not msgspec.UNSET:
            base = auto_patched if auto_patched is not None else dict(existing_progress)
            explicit = {k: v for k, v in msgspec.structs.asdict(data.progress).items() if v is not msgspec.UNSET}
            base.update(explicit)
            progress_dict = base
        else:
            progress_dict = auto_patched

        await self._store_repo.admin_update_user_quest(
            progress_id,
            quest_data=quest_data_dict,
            progress=progress_dict,
            completed_at=completed_at,
        )

        return AdminUpdateUserQuestResponse(success=True)

    async def update_config(
        self,
        *,
        rotation_period_days: int | None = None,
        active_key_type: str | None = None,
    ) -> None:
        """Update store configuration.

        Args:
            rotation_period_days: New rotation period.
            active_key_type: New active key type.
        """
        if active_key_type is not None:
            await self._ensure_key_type_exists(active_key_type)

        await self._store_repo.update_config(
            rotation_period_days=rotation_period_days,
            active_key_type=active_key_type,
        )

    async def get_quest_config(self) -> QuestConfigResponse:
        """Get quest configuration."""
        config = await self._store_repo.fetch_quest_config()
        return msgspec.convert(config, QuestConfigResponse)

    async def update_quest_config(
        self,
        *,
        rotation_day: int | None = None,
        rotation_hour: int | None = None,
        easy_quest_count: int | None = None,
        medium_quest_count: int | None = None,
        hard_quest_count: int | None = None,
    ) -> UpdateQuestConfigResponse:
        """Update quest configuration and recompute next_rotation_at if needed."""
        config = await self._store_repo.fetch_quest_config()
        updates: dict[str, object] = {}

        if rotation_day is not None:
            updates["rotation_day"] = rotation_day
        if rotation_hour is not None:
            updates["rotation_hour"] = rotation_hour
        if easy_quest_count is not None:
            updates["easy_quest_count"] = easy_quest_count
        if medium_quest_count is not None:
            updates["medium_quest_count"] = medium_quest_count
        if hard_quest_count is not None:
            updates["hard_quest_count"] = hard_quest_count

        if "rotation_day" in updates or "rotation_hour" in updates:
            new_day = cast(int, updates.get("rotation_day") or config.get("rotation_day") or 1)
            new_hour = cast(int, updates.get("rotation_hour") or config.get("rotation_hour") or 0)
            now = datetime.datetime.now(datetime.timezone.utc)
            candidate = now.replace(hour=new_hour, minute=0, second=0, microsecond=0)
            weekday = candidate.isoweekday()
            shift_days = (new_day - weekday) % 7
            candidate = candidate + datetime.timedelta(days=shift_days)
            if candidate <= now:
                candidate = candidate + datetime.timedelta(days=7)
            updates["next_rotation_at"] = candidate

        await self._store_repo.update_quest_config(updates)
        return UpdateQuestConfigResponse(
            success=True,
            updated_fields=list(updates.keys()),
            next_rotation_at=cast(
                "datetime.datetime | None",
                updates.get("next_rotation_at", config.get("next_rotation_at")),
            ),
        )

    async def generate_quest_rotation(self) -> GenerateQuestRotationResponse:
        """Manually trigger quest rotation generation."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM store.check_and_generate_quest_rotation()")
        if not row:
            raise RuntimeError("Quest rotation generation failed.")
        return GenerateQuestRotationResponse(
            rotation_id=row["rotation_id"],
            generated=row["generated"],
            auto_claimed_quests=row["auto_claimed"],
            global_quests_generated=row["global_quests_generated"],
        )


async def provide_store_service(state: State) -> StoreService:
    """Litestar DI provider for store service.

    Args:
        state: Application state.

    Returns:
        StoreService instance.
    """
    store_repo = StoreRepository(pool=state.db_pool)
    lootbox_repo = LootboxRepository(pool=state.db_pool)
    return StoreService(pool=state.db_pool, state=state, store_repo=store_repo, lootbox_repo=lootbox_repo)
