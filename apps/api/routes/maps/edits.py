"""Map edit request routes for managing edit suggestions and approvals."""

from __future__ import annotations

import datetime as dt
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
from genjishimada_sdk.newsfeed import (
    NewsfeedArchive,
    NewsfeedEvent,
    NewsfeedUnarchive,
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
        "newsfeed": Provide(provide_newsfeed_service),
        "users": Provide(provide_user_service),
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
        edit_request = await svc.create_edit_request(
            code=data.code,
            proposed_changes=data.to_changes_dict(),
            reason=data.reason,
            created_by=data.created_by,
        )

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
        edit_id: int,
    ) -> MapEditSubmissionResponse:
        """Get an edit request with human-readable changes."""
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
    async def resolve_edit_request(  # noqa: PLR0913
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
            # Get original map data for newsfeed comparison
            original_map = await maps.fetch_maps(
                single=True,
                filters=MapSearchFilters(code=edit_request.code),
            )

            # Convert changes to patch data
            patch_data = svc.convert_changes_to_patch(edit_request.proposed_changes)

            # Handle archive separately - it needs special newsfeed event
            has_archive_change = "archived" in edit_request.proposed_changes
            remaining_changes: dict = {}

            if has_archive_change:
                archived_value = edit_request.proposed_changes["archived"]

                # Perform the archive/unarchive operation
                if archived_value:
                    await maps.archive_map(edit_request.code)
                    # Generate archive newsfeed event
                    payload = NewsfeedArchive(
                        code=edit_request.code,
                        map_name=original_map.map_name,
                        creators=[c.name for c in original_map.creators],
                        difficulty=original_map.difficulty,
                        reason=edit_request.reason,
                    )
                    event_type = "archive"
                else:
                    await maps.unarchive_map(edit_request.code)
                    # Generate unarchive newsfeed event
                    payload = NewsfeedUnarchive(
                        code=edit_request.code,
                        map_name=original_map.map_name,
                        creators=[c.name for c in original_map.creators],
                        difficulty=original_map.difficulty,
                        reason=edit_request.reason,
                    )
                    event_type = "unarchive"

                # Publish archive/unarchive newsfeed
                event = NewsfeedEvent(
                    id=None,
                    timestamp=dt.datetime.now(dt.timezone.utc),
                    payload=payload,
                    event_type=event_type,
                )
                await newsfeed.create_and_publish(event, headers=request.headers)

                # Prepare remaining changes (without archived)
                remaining_changes = {k: v for k, v in edit_request.proposed_changes.items() if k != "archived"}

                # Apply remaining changes if any
                if remaining_changes:
                    patch_data = svc.convert_changes_to_patch(remaining_changes)
                    await maps.patch_map(edit_request.code, patch_data)
            else:
                # No archive change, apply patch normally
                await maps.patch_map(edit_request.code, patch_data)
                remaining_changes = edit_request.proposed_changes

            # Generate newsfeed entry for non-archive changes
            if remaining_changes:

                async def _get_user_coalesced_name(user_id: int) -> str:
                    d = await users.get_user(user_id)
                    if d:
                        return d.coalesced_name or "Unknown User"
                    return "Unknown User"

                # Build patch for newsfeed (without archived field)
                newsfeed_patch = svc.convert_changes_to_patch(remaining_changes)

                await newsfeed.generate_map_edit_newsfeed(
                    original_map,
                    newsfeed_patch,
                    edit_request.reason,
                    request.headers,
                    get_creator_name=_get_user_coalesced_name,
                )

        # Mark as resolved
        await svc.resolve_request(
            edit_id=edit_id,
            accepted=data.accepted,
            resolved_by=data.resolved_by,
            rejection_reason=data.rejection_reason,
        )

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
