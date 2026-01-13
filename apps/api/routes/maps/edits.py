# apps/api/routes/maps/edits.py

from __future__ import annotations

from logging import getLogger

import litestar
from genjishimada_sdk.maps import (
    MapEditCreatedEvent,
    MapEditCreateRequest,
    MapEditResolvedEvent,
    MapEditResolveRequest,
    MapEditResponse,
    MapEditSetMessageIdRequest,
    MapEditSubmissionResponse,
    PendingMapEditResponse,
)
from litestar.di import Provide

from di import (
    MapEditService,
    MapService,
    NewsfeedService,
    UserService,
    provide_map_edit_service,
    provide_map_service,
    provide_newsfeed_service,
    provide_user_service,
)
from di.maps import MapSearchFilters

log = getLogger(__name__)


class MapEditsController(litestar.Controller):
    """Map Edit Requests."""

    tags = ["Map Edits"]
    path = "/map-edits"
    dependencies = {
        "svc": Provide(provide_map_edit_service),
        "maps": Provide(provide_map_service),
        "users": Provide(provide_user_service),
        "newsfeed": Provide(provide_newsfeed_service),
    }

    @litestar.post(
        path="/",
        summary="Create Map Edit Request",
        description="Submit a map edit request for moderator approval.",
    )
    async def create_edit_request(
        self,
        request: litestar.Request,
        svc: MapEditService,
        data: MapEditCreateRequest,
    ) -> MapEditResponse:
        """Create a new map edit request."""
        edit_request = await svc.create_edit_request(data)

        # Publish event for bot to pick up
        await svc.publish_message(
            routing_key="api.map_edit.created",
            data=MapEditCreatedEvent(edit_request_id=edit_request.id),
            headers=request.headers,
            idempotency_key=f"map_edit:created:{edit_request.id}",
        )

        return edit_request

    @litestar.get(
        path="/pending",
        summary="Get Pending Edit Requests",
        description="Retrieve all map edit requests awaiting approval.",
    )
    async def get_pending_edit_requests(
        self,
        svc: MapEditService,
    ) -> list[PendingMapEditResponse]:
        """Get all pending edit requests."""
        return await svc.get_pending_requests()

    @litestar.get(
        path="/{edit_id:int}",
        summary="Get Edit Request",
        description="Get a specific edit request by ID.",
    )
    async def get_edit_request(
        self,
        svc: MapEditService,
        edit_id: int,
    ) -> MapEditResponse:
        """Get a specific edit request."""
        return await svc.get_edit_request(edit_id)

    @litestar.get(
        path="/{edit_id:int}/submission",
        summary="Get Edit Request Submission View",
        description="Get enriched edit request data for the verification queue.",
    )
    async def get_edit_submission(
        self,
        svc: MapEditService,
        users: UserService,
        edit_id: int,
    ) -> MapEditSubmissionResponse:
        """Get edit request with human-readable changes."""
        return await svc.get_edit_submission(edit_id)

    @litestar.patch(
        path="/{edit_id:int}/message",
        summary="Set Message ID",
        description="Associate a Discord message ID with an edit request.",
    )
    async def set_message_id(
        self,
        svc: MapEditService,
        edit_id: int,
        data: MapEditSetMessageIdRequest,
    ) -> None:
        """Set the verification queue message ID."""
        await svc.set_message_id(edit_id, data.message_id)

    @litestar.put(
        path="/{edit_id:int}/resolve",
        summary="Resolve Edit Request",
        description="Accept or reject a map edit request.",
    )
    async def resolve_edit_request(
        self,
        request: litestar.Request,
        svc: MapEditService,
        maps: MapService,
        newsfeed: NewsfeedService,
        users: UserService,
        edit_id: int,
        data: MapEditResolveRequest,
    ) -> None:
        """Resolve an edit request (accept or reject)."""
        edit_request = await svc.get_edit_request(edit_id)

        if data.accepted:
            # Apply the changes
            patch_data = svc.convert_changes_to_patch(edit_request.proposed_changes)
            await maps.patch_map(edit_request.code, patch_data)

            # Generate newsfeed entry
            original_map = await maps.fetch_maps(filters=MapSearchFilters(code=edit_request.code), single=True)
            # ... newsfeed logic similar to existing patch endpoint

        # Mark as resolved
        await svc.resolve_request(edit_id, data)

        # Publish event for bot notification
        await svc.publish_message(
            routing_key="api.map_edit.resolved",
            data=MapEditResolvedEvent(
                edit_request_id=edit_id,
                accepted=data.accepted,
                resolved_by=data.resolved_by,
                rejection_reason=data.rejection_reason,
            ),
            headers=request.headers,
            idempotency_key=f"map_edit:resolved:{edit_id}",
        )

    @litestar.get(
        path="/user/{user_id:int}",
        summary="Get User's Edit Requests",
        description="Get all edit requests submitted by a user.",
    )
    async def get_user_edit_requests(
        self,
        svc: MapEditService,
        user_id: int,
        include_resolved: bool = False,
    ) -> list[MapEditResponse]:
        """Get edit requests for a specific user."""
        return await svc.get_user_requests(user_id, include_resolved)
