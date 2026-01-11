from __future__ import annotations

import logging

import litestar
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
from litestar.di import Provide
from litestar.status_codes import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from di.notifications import NotificationService, provide_notification_service

log = logging.getLogger(__name__)


class NotificationsController(litestar.Controller):
    """Notifications API controller."""

    tags = ["Notifications"]
    path = "/notifications"
    dependencies = {"svc": Provide(provide_notification_service)}

    @litestar.post(
        path="/events",
        summary="Create Notification",
        description="Create a notification event and dispatch for delivery.",
        status_code=HTTP_201_CREATED,
    )
    async def create_notification(
        self,
        svc: NotificationService,
        data: NotificationCreateRequest,
        request: litestar.Request,
    ) -> NotificationEventResponse:
        """Create a notification event.

        This endpoint stores the notification and dispatches it to RabbitMQ
        for Discord delivery if the user is a Discord user.

        Args:
            svc: Notification service.
            data: Notification creation request.
            request: Request to get the headers

        Returns:
            The created notification event.
        """
        return await svc.create_and_dispatch(data, request.headers)

    @litestar.get(
        path="/users/{user_id:int}/events",
        summary="Get User Notifications",
        description="Get notifications for a user's notification tray.",
    )
    async def get_user_events(
        self,
        svc: NotificationService,
        user_id: int,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationEventResponse]:
        """Get notification events for a user.

        Args:
            svc: Notification service.
            user_id: Target user ID.
            unread_only: Only return unread notifications.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of notification events.
        """
        return await svc.get_user_events(user_id, unread_only=unread_only, limit=limit, offset=offset)

    @litestar.get(
        path="/users/{user_id:int}/unread-count",
        summary="Get Unread Count",
        description="Get count of unread notifications for badge display.",
    )
    async def get_unread_count(
        self,
        svc: NotificationService,
        user_id: int,
    ) -> NotificationUnreadCountResponse:
        """Get unread notification count.

        Args:
            svc: Notification service.
            user_id: Target user ID.

        Returns:
            Unread count response.
        """
        count = await svc.get_unread_count(user_id)
        return NotificationUnreadCountResponse(count=count)

    @litestar.patch(
        path="/events/{event_id:int}/read",
        summary="Mark Notification Read",
        description="Mark a single notification as read.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def mark_read(
        self,
        svc: NotificationService,
        event_id: int,
    ) -> None:
        """Mark a notification as read.

        Args:
            svc: Notification service.
            event_id: ID of the notification event.
        """
        await svc.mark_read(event_id)

    @litestar.patch(
        path="/users/{user_id:int}/read-all",
        summary="Mark All Read",
        description="Mark all notifications as read for a user.",
    )
    async def mark_all_read(
        self,
        svc: NotificationService,
        user_id: int,
    ) -> dict[str, int]:
        """Mark all notifications as read.

        Args:
            svc: Notification service.
            user_id: Target user ID.

        Returns:
            Count of notifications marked as read.
        """
        count = await svc.mark_all_read(user_id)
        return {"marked_read": count}

    @litestar.patch(
        path="/events/{event_id:int}/dismiss",
        summary="Dismiss Notification",
        description="Dismiss a notification from the tray.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def dismiss_event(
        self,
        svc: NotificationService,
        event_id: int,
    ) -> None:
        """Dismiss a notification.

        Args:
            svc: Notification service.
            event_id: ID of the notification event.
        """
        await svc.dismiss_event(event_id)

    @litestar.post(
        path="/events/{event_id:int}/delivery-result",
        summary="Record Delivery Result",
        description="Record the result of a notification delivery attempt.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def record_delivery_result(
        self,
        svc: NotificationService,
        event_id: int,
        data: NotificationDeliveryResultRequest,
    ) -> None:
        """Record delivery result from bot.

        Args:
            svc: Notification service.
            event_id: ID of the notification event.
            data: Delivery result data.
        """
        await svc.record_delivery_result(
            event_id=event_id,
            channel=data.channel,
            status=data.status,
            error_message=data.error_message,
        )

    @litestar.get(
        path="/users/{user_id:int}/preferences",
        summary="Get User Preferences",
        description="Get all notification preferences for a user.",
    )
    async def get_preferences(
        self,
        svc: NotificationService,
        user_id: int,
    ) -> list[NotificationPreferencesResponse]:
        """Get notification preferences.

        Args:
            svc: Notification service.
            user_id: Target user ID.

        Returns:
            List of preferences grouped by event type.
        """
        return await svc.get_preferences(user_id)

    @litestar.put(
        path="/users/{user_id:int}/preferences/{event_type:str}/{channel:str}",
        summary="Update Single Preference",
        description="Update a single notification preference.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def update_preference(
        self,
        svc: NotificationService,
        user_id: int,
        event_type: NOTIFICATION_EVENT_TYPE,
        channel: NOTIFICATION_CHANNEL,
        enabled: bool,
    ) -> None:
        """Update a single preference.

        Args:
            svc: Notification service.
            user_id: Target user ID.
            event_type: Event type string.
            channel: Channel string.
            enabled: Whether the preference is enabled.
        """
        await svc.update_preference(user_id, event_type, channel, enabled)

    @litestar.put(
        path="/users/{user_id:int}/preferences/bulk",
        summary="Bulk Update Preferences",
        description="Update multiple notification preferences at once.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def bulk_update_preferences(
        self,
        svc: NotificationService,
        user_id: int,
        data: list[NotificationPreference],
    ) -> None:
        """Bulk update preferences.

        Args:
            svc: Notification service.
            user_id: Target user ID.
            data: List of preference updates.
        """
        await svc.bulk_update_preferences(user_id, data)

    @litestar.get(
        path="/users/{user_id:int}/should-deliver",
        summary="Check Should Deliver",
        description="Check if a notification should be delivered to a channel.",
    )
    async def should_deliver(
        self,
        svc: NotificationService,
        user_id: int,
        event_type: NOTIFICATION_EVENT_TYPE,
        channel: NOTIFICATION_CHANNEL,
    ) -> ShouldDeliverResponse:
        """Check if notification should be delivered.

        Args:
            svc: Notification service.
            user_id: Target user ID.
            event_type: Event type to check.
            channel: Channel to check.

        Returns:
            Whether notification should be delivered.
        """
        result = await svc.should_deliver(user_id, event_type, channel)
        return ShouldDeliverResponse(should_deliver=result)

    @litestar.get(
        path="/users/{user_id:int}/legacy-bitmask",
        summary="Get Legacy Bitmask",
        description="Get notification preferences as legacy bitmask for bot compatibility.",
    )
    async def get_legacy_bitmask(
        self,
        svc: NotificationService,
        user_id: int,
    ) -> dict[str, int]:
        """Get legacy bitmask.

        Args:
            svc: Notification service.
            user_id: Target user ID.

        Returns:
            Legacy bitmask value.
        """
        bitmask = await svc.get_legacy_bitmask(user_id)
        return {"bitmask": bitmask}
