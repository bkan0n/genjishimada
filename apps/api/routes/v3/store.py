"""Store v3 controller."""

from __future__ import annotations

from typing import Annotated

import litestar
from genjishimada_sdk.store import (
    GenerateRotationRequest,
    ItemPurchaseRequest,
    ItemPurchaseResponse,
    KeyPricingResponse,
    KeyPurchaseRequest,
    KeyPurchaseResponse,
    PurchaseHistoryResponse,
    RotationResponse,
    StoreConfigResponse,
    UpdateConfigRequest,
)
from litestar.di import Provide
from litestar.params import Body
from litestar.status_codes import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_402_PAYMENT_REQUIRED, HTTP_409_CONFLICT

from repository.store_repository import provide_store_repository
from services.exceptions.store import (
    AlreadyOwnedError,
    InsufficientCoinsError,
    InvalidQuantityError,
    ItemNotInRotationError,
    RotationExpiredError,
)
from services.store_service import StoreService, provide_store_service
from utilities.errors import CustomHTTPException


class StoreController(litestar.Controller):
    """Store v3 controller."""

    tags = ["Store"]
    path = "/store"
    dependencies = {
        "store_repo": Provide(provide_store_repository),
        "store_service": Provide(provide_store_service),
    }

    @litestar.get(
        path="/rotation",
        summary="Get Current Rotation",
        description="Get currently available items in the rotating store.",
    )
    async def get_rotation(
        self,
        store_service: StoreService,
        user_id: int | None = None,
    ) -> RotationResponse:
        """Get current rotation.

        Args:
            store_service: Store service.
            user_id: Optional user ID to check ownership.

        Returns:
            Current rotation with items.
        """
        return await store_service.get_current_rotation(user_id=user_id)

    @litestar.get(
        path="/keys",
        summary="Get Key Pricing",
        description="Get key pricing for all key types with bulk discounts.",
    )
    async def get_key_pricing(
        self,
        store_service: StoreService,
    ) -> dict[str, str | list[KeyPricingResponse]]:
        """Get key pricing.

        Args:
            store_service: Store service.

        Returns:
            Key pricing information with active key type.
        """
        config = await store_service.get_config()
        pricing = await store_service.get_key_pricing()

        return {
            "active_key_type": config.active_key_type,
            "keys": pricing,
        }

    @litestar.post(
        path="/purchase/keys",
        summary="Purchase Keys",
        description="Purchase lootbox keys with coins.",
        status_code=HTTP_200_OK,
    )
    async def purchase_keys(
        self,
        store_service: StoreService,
        data: Annotated[KeyPurchaseRequest, Body()],
    ) -> KeyPurchaseResponse:
        """Purchase keys.

        Args:
            store_service: Store service.
            data: Purchase request.

        Returns:
            Purchase response.

        Raises:
            CustomHTTPException: On validation or business logic errors.
        """
        try:
            return await store_service.purchase_keys(
                user_id=data.user_id,
                key_type=data.key_type,
                quantity=data.quantity,
            )
        except InvalidQuantityError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e
        except InsufficientCoinsError as e:
            raise CustomHTTPException(
                status_code=HTTP_402_PAYMENT_REQUIRED,
                detail=str(e),
            ) from e

    @litestar.post(
        path="/purchase/item",
        summary="Purchase Item",
        description="Purchase an item from the current rotation.",
        status_code=HTTP_200_OK,
    )
    async def purchase_item(
        self,
        store_service: StoreService,
        data: Annotated[ItemPurchaseRequest, Body()],
    ) -> ItemPurchaseResponse:
        """Purchase item.

        Args:
            store_service: Store service.
            data: Purchase request.

        Returns:
            Purchase response.

        Raises:
            CustomHTTPException: On validation or business logic errors.
        """
        try:
            return await store_service.purchase_item(
                user_id=data.user_id,
                item_name=data.item_name,
                item_type=data.item_type,
                key_type=data.key_type,
            )
        except ItemNotInRotationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e
        except (RotationExpiredError, AlreadyOwnedError) as e:
            status = HTTP_409_CONFLICT if isinstance(e, AlreadyOwnedError) else HTTP_400_BAD_REQUEST
            raise CustomHTTPException(
                status_code=status,
                detail=str(e),
            ) from e
        except InsufficientCoinsError as e:
            raise CustomHTTPException(
                status_code=HTTP_402_PAYMENT_REQUIRED,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/users/{user_id:int}/purchases",
        summary="Get Purchase History",
        description="Get user's store purchase history.",
    )
    async def get_purchase_history(
        self,
        store_service: StoreService,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> PurchaseHistoryResponse:
        """Get purchase history.

        Args:
            store_service: Store service.
            user_id: User ID.
            limit: Max results.
            offset: Result offset.

        Returns:
            Purchase history.
        """
        return await store_service.get_user_purchases(user_id, limit, offset)

    @litestar.post(
        path="/admin/rotation/generate",
        summary="Generate New Rotation (Admin)",
        description="Manually trigger new rotation generation.",
        status_code=HTTP_200_OK,
    )
    async def generate_rotation(
        self,
        store_service: StoreService,
        data: Annotated[GenerateRotationRequest, Body()] | None = None,
    ) -> dict:
        """Generate new rotation.

        Args:
            store_service: Store service.
            data: Optional generation parameters.

        Returns:
            Generation result.
        """
        item_count = data.item_count if data else 5
        return await store_service.generate_rotation(item_count)

    @litestar.get(
        path="/admin/config",
        summary="Get Store Config (Admin)",
        description="View current store configuration.",
    )
    async def get_config(
        self,
        store_service: StoreService,
    ) -> StoreConfigResponse:
        """Get store config.

        Args:
            store_service: Store service.

        Returns:
            Store configuration.
        """
        return await store_service.get_config()

    @litestar.put(
        path="/admin/config",
        summary="Update Store Config (Admin)",
        description="Update store configuration.",
        status_code=HTTP_200_OK,
    )
    async def update_config(
        self,
        store_service: StoreService,
        data: Annotated[UpdateConfigRequest, Body()],
    ) -> StoreConfigResponse:
        """Update store config.

        Args:
            store_service: Store service.
            data: Config update request.

        Returns:
            Updated configuration.
        """
        await store_service.update_config(
            rotation_period_days=data.rotation_period_days,
            active_key_type=data.active_key_type,
        )
        return await store_service.get_config()
