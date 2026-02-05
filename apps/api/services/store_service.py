"""Service layer for store domain business logic."""

from __future__ import annotations

import datetime
import logging
from typing import cast
from uuid import UUID

import msgspec
from asyncpg import Pool
from genjishimada_sdk.lootbox import LootboxKeyType
from genjishimada_sdk.store import (
    GenerateRotationResponse,
    ItemPurchaseResponse,
    KeyPriceInfo,
    KeyPricingResponse,
    KeyPurchaseResponse,
    PurchaseHistoryResponse,
    RotationItemResponse,
    RotationResponse,
    StoreConfigResponse,
)
from litestar.datastructures import State

from repository.lootbox_repository import LootboxRepository
from repository.store_repository import StoreRepository
from services.base import BaseService
from services.exceptions.store import (
    AlreadyOwnedError,
    InsufficientCoinsError,
    InvalidQuantityError,
    ItemNotInRotationError,
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
            InsufficientCoinsError: If user doesn't have enough coins.
        """
        if quantity not in [1, 3, 5]:
            raise InvalidQuantityError(quantity)

        config = await self._store_repo.fetch_config()
        is_active = key_type == config["active_key_type"]

        price = self._calculate_key_price(quantity, is_active)

        async with self._pool.acquire() as conn, conn.transaction():
            user_coins = await self._lootbox_repo.fetch_user_coins(user_id, conn=conn)  # type: ignore[arg-type]
            if user_coins < price:
                raise InsufficientCoinsError(user_coins, price)

            await self._lootbox_repo.add_user_coins(user_id, -price, conn=conn)  # type: ignore[arg-type]

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

            remaining_coins = user_coins - price

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

            user_coins = await self._lootbox_repo.fetch_user_coins(user_id, conn=conn)  # type: ignore[arg-type]
            if user_coins < price:
                raise InsufficientCoinsError(user_coins, price)

            await self._lootbox_repo.add_user_coins(user_id, -price, conn=conn)  # type: ignore[arg-type]

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

            remaining_coins = user_coins - price

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

    async def generate_rotation(self, item_count: int = 5) -> GenerateRotationResponse:
        """Generate a new store rotation.

        Args:
            item_count: Number of items to generate.

        Returns:
            Rotation generation result.
        """
        result = await self._store_repo.generate_rotation(item_count)
        return msgspec.convert(result, GenerateRotationResponse)

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
        await self._store_repo.update_config(
            rotation_period_days=rotation_period_days,
            active_key_type=active_key_type,
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
