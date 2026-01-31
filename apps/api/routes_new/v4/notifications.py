"""V4 Notifications routes."""

from __future__ import annotations

from typing import Annotated

from genjishimada_sdk.notifications import (
    NOTIFICATION_CHANNEL,
    NOTIFICATION_EVENT_TYPE,
    NotificationCreateRequest,
    NotificationDeliveryResultRequest,
    NotificationEventResponse,
    NotificationPreference,
    NotificationPreferencesResponse,
    NotificationUnreadCountResponse,
    ShouldDeliverResponse,
)
from litestar import Controller, Request, get, patch, post, put
from litestar.datastructures import State
from litestar.di import Provide
from litestar.params import Parameter
from litestar.status_codes import HTTP_201_CREATED, HTTP_204_NO_CONTENT, HTTP_404_NOT_FOUND

from repository.notifications_repository import NotificationsRepository
from services.exceptions.users import UserNotFoundError
from services.notifications_service import NotificationsService
from utilities.errors import CustomHTTPException


async def provide_notifications_repository(state: State) -> NotificationsRepository:
    """Litestar DI provider for notifications repository.

    Args:
        state: Application state.

    Returns:
        Repository instance.
    """
    return NotificationsRepository(pool=state.db_pool)


async def provide_notifications_service(
    state: State,
    notifications_repo: NotificationsRepository,
) -> NotificationsService:
    """Litestar DI provider for notifications service.

    Args:
        state: Application state.
        notifications_repo: Notifications repository instance.

    Returns:
        Service instance.
    """
    return NotificationsService(pool=state.db_pool, state=state, notifications_repo=notifications_repo)


class NotificationsController(Controller):
    """Controller for notifications endpoints."""

    tags = ["Notifications"]
    path = "/notifications"
    dependencies = {
        "notifications_repo": Provide(provide_notifications_repository),
        "notifications_service": Provide(provide_notifications_service),
    }

    @post(
        "/events",
        summary="Create Notification",
        description="Create a notification event and dispatch for delivery.",
        status_code=HTTP_201_CREATED,
    )
    async def create_notification(
        self,
        request: Request,
        data: NotificationCreateRequest,
        notifications_service: NotificationsService,
    ) -> NotificationEventResponse:
        """Create a notification event.

        This endpoint stores the notification and dispatches it to RabbitMQ
        for Discord delivery if the user is a Discord user.

        Args:
            request: Request to get the headers.
            data: Notification creation request.
            notifications_service: Service dependency.

        Returns:
            The created notification event (201 Created from decorator).

        Raises:
            CustomHTTPException: 404 if user does not exist.
        """
        try:
            return await notifications_service.create_and_dispatch(data, request.headers)
        except UserNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=e.message,
            ) from e

    @get(
        "/users/{user_id:int}/events",
        summary="Get User Notifications",
        description="Get notifications for a user's notification tray.",
    )
    async def get_user_events(
        self,
        user_id: int,
        notifications_service: NotificationsService,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationEventResponse]:
        """Get notification events for a user.

        Args:
            user_id: Target user ID.
            notifications_service: Service dependency.
            unread_only: Only return unread notifications.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of notification events (200 OK automatic).
        """
        return await notifications_service.get_user_events(user_id, unread_only=unread_only, limit=limit, offset=offset)

    @get(
        "/users/{user_id:int}/unread-count",
        summary="Get Unread Count",
        description="Get count of unread notifications for badge display.",
    )
    async def get_unread_count(
        self,
        user_id: int,
        notifications_service: NotificationsService,
    ) -> NotificationUnreadCountResponse:
        """Get unread notification count.

        Args:
            user_id: Target user ID.
            notifications_service: Service dependency.

        Returns:
            Unread count response (200 OK automatic).
        """
        count = await notifications_service.get_unread_count(user_id)
        return NotificationUnreadCountResponse(count=count)

    @patch(
        "/events/{event_id:int}/read",
        summary="Mark Notification Read",
        description="Mark a single notification as read.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def mark_read(
        self,
        event_id: int,
        notifications_service: NotificationsService,
    ) -> None:
        """Mark a notification as read.

        Args:
            event_id: ID of the notification event.
            notifications_service: Service dependency.

        Returns:
            None (204 No Content from decorator).
        """
        await notifications_service.mark_read(event_id)

    @patch(
        "/users/{user_id:int}/read-all",
        summary="Mark All Read",
        description="Mark all notifications as read for a user.",
    )
    async def mark_all_read(
        self,
        user_id: int,
        notifications_service: NotificationsService,
    ) -> dict[str, int]:
        """Mark all notifications as read.

        Args:
            user_id: Target user ID.
            notifications_service: Service dependency.

        Returns:
            Count of notifications marked as read (200 OK automatic).
        """
        count = await notifications_service.mark_all_read(user_id)
        return {"marked_read": count}

    @patch(
        "/events/{event_id:int}/dismiss",
        summary="Dismiss Notification",
        description="Dismiss a notification from the tray.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def dismiss_event(
        self,
        event_id: int,
        notifications_service: NotificationsService,
    ) -> None:
        """Dismiss a notification.

        Args:
            event_id: ID of the notification event.
            notifications_service: Service dependency.

        Returns:
            None (204 No Content from decorator).
        """
        await notifications_service.dismiss_event(event_id)

    @post(
        "/events/{event_id:int}/delivery-result",
        summary="Record Delivery Result",
        description="Record the result of a notification delivery attempt.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def record_delivery_result(
        self,
        event_id: int,
        data: NotificationDeliveryResultRequest,
        notifications_service: NotificationsService,
    ) -> None:
        """Record delivery result from bot.

        Args:
            event_id: ID of the notification event.
            data: Delivery result data.
            notifications_service: Service dependency.

        Returns:
            None (204 No Content from decorator).
        """
        await notifications_service.record_delivery_result(
            event_id=event_id,
            channel=data.channel,
            status=data.status,
            error_message=data.error_message,
        )

    @get(
        "/users/{user_id:int}/preferences",
        summary="Get User Preferences",
        description="Get all notification preferences for a user.",
    )
    async def get_preferences(
        self,
        user_id: int,
        notifications_service: NotificationsService,
    ) -> list[NotificationPreferencesResponse]:
        """Get notification preferences.

        Args:
            user_id: Target user ID.
            notifications_service: Service dependency.

        Returns:
            List of preferences grouped by event type (200 OK automatic).
        """
        return await notifications_service.get_preferences(user_id)

    @put(
        "/users/{user_id:int}/preferences/{event_type:str}/{channel:str}",
        summary="Update Single Preference",
        description="Update a single notification preference.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def update_preference(
        self,
        user_id: int,
        event_type: Annotated[NOTIFICATION_EVENT_TYPE, Parameter()],
        channel: Annotated[NOTIFICATION_CHANNEL, Parameter()],
        notifications_service: NotificationsService,
        enabled: bool,
    ) -> None:
        """Update a single preference.

        Args:
            user_id: Target user ID.
            event_type: Event type string.
            channel: Channel string.
            notifications_service: Service dependency.
            enabled: Whether the preference is enabled.

        Returns:
            None (204 No Content from decorator).

        Raises:
            CustomHTTPException: 404 if user does not exist.
        """
        try:
            await notifications_service.update_preference(user_id, event_type, channel, enabled)
        except UserNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=e.message,
            ) from e

    @put(
        "/users/{user_id:int}/preferences/bulk",
        summary="Bulk Update Preferences",
        description="Update multiple notification preferences at once.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def bulk_update_preferences(
        self,
        user_id: int,
        data: list[NotificationPreference],
        notifications_service: NotificationsService,
    ) -> None:
        """Bulk update preferences.

        Args:
            user_id: Target user ID.
            data: List of preference updates.
            notifications_service: Service dependency.

        Returns:
            None (204 No Content from decorator).
        """
        await notifications_service.bulk_update_preferences(user_id, data)

    @get(
        "/users/{user_id:int}/should-deliver",
        summary="Check Should Deliver",
        description="Check if a notification should be delivered to a channel.",
    )
    async def should_deliver(
        self,
        user_id: int,
        event_type: Annotated[NOTIFICATION_EVENT_TYPE, Parameter()],
        channel: Annotated[NOTIFICATION_CHANNEL, Parameter()],
        notifications_service: NotificationsService,
    ) -> ShouldDeliverResponse:
        """Check if notification should be delivered.

        Args:
            user_id: Target user ID.
            event_type: Event type to check.
            channel: Channel to check.
            notifications_service: Service dependency.

        Returns:
            Whether notification should be delivered (200 OK automatic).
        """
        result = await notifications_service.should_deliver(user_id, event_type, channel)
        return ShouldDeliverResponse(should_deliver=result)
