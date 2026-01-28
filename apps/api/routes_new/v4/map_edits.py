"""V4 map edit request routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from genjishimada_sdk.maps import (
    MapEditCreateRequest,
    MapEditResponse,
    MapEditResolveRequest,
    MapEditSetMessageIdRequest,
    MapEditSubmissionResponse,
    PendingMapEditResponse,
)
from litestar import Controller, Request, get, patch, post, put
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import (
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from repository.maps_repository import provide_maps_repository
from services.exceptions.maps import (
    EditRequestNotFoundError,
    MapNotFoundError,
    PendingEditRequestExistsError,
)
from services.maps_service import MapsService, provide_maps_service
from services.newsfeed_service import NewsfeedService, provide_newsfeed_service
from services.notifications_service import (
    NotificationService,
    provide_notifications_service,
)
from services.users_service import UserService, provide_users_service
from utilities.errors import CustomHTTPException

if TYPE_CHECKING:
    pass


class MapEditsController(Controller):
    """Controller for map edit request endpoints."""

    tags = ["Map Edits"]
    path = "/map-edits"
    dependencies = {
        "maps_repo": Provide(provide_maps_repository),
        "maps_service": Provide(provide_maps_service),
        "newsfeed_service": Provide(provide_newsfeed_service),
        "users_service": Provide(provide_users_service),
        "notifications_service": Provide(provide_notifications_service),
    }

    @post(
        "/",
        summary="Create Map Edit Request",
        description="Submit a map edit request for moderator approval.",
    )
    async def create_edit_request_endpoint(
        self,
        request: Request,
        data: Annotated[MapEditCreateRequest, Body(title="Edit request")],
        maps_service: MapsService,
    ) -> MapEditResponse:
        """Create a new map edit request.

        Args:
            request: Request object.
            data: Edit request data.
            maps_service: Maps service.

        Returns:
            Created edit request.

        Raises:
            CustomHTTPException: On validation or business rule errors.
        """
        try:
            return await maps_service.create_edit_request(
                code=data.code,
                proposed_changes=data.to_changes_dict(),
                reason=data.reason,
                created_by=data.created_by,
                headers=request.headers,
            )

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"Map with code {e.message} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except PendingEditRequestExistsError as e:
            raise CustomHTTPException(
                detail="There is already a pending edit request for this map.",
                status_code=HTTP_409_CONFLICT,
                extra={"edit_request_id": e.context.get("existing_edit_id")},
            ) from e

    @get(
        "/pending",
        summary="Get Pending Edit Requests",
        description="Retrieve all map edit requests awaiting approval.",
    )
    async def get_pending_requests_endpoint(
        self,
        maps_service: MapsService,
    ) -> list[PendingMapEditResponse]:
        """Get all pending edit requests."""
        return await maps_service.get_pending_requests()

    @get(
        "/{edit_id:int}",
        summary="Get Edit Request",
        description="Get a specific edit request by ID.",
    )
    async def get_edit_request_endpoint(
        self,
        edit_id: int,
        maps_service: MapsService,
    ) -> MapEditResponse:
        """Get a specific edit request.

        Args:
            edit_id: Edit request ID.
            maps_service: Maps service.

        Returns:
            Edit request.

        Raises:
            CustomHTTPException: If not found.
        """
        try:
            return await maps_service.get_edit_request(edit_id)

        except EditRequestNotFoundError:
            raise CustomHTTPException(
                detail=f"Edit request {edit_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from None

    @get(
        "/{edit_id:int}/submission",
        summary="Get Edit Request Submission View",
        description="Get enriched edit request data for the verification queue.",
    )
    async def get_edit_submission_endpoint(
        self,
        edit_id: int,
        maps_service: MapsService,
        users_service: UserService,
    ) -> MapEditSubmissionResponse:
        """Get enriched edit submission data.

        Args:
            edit_id: Edit request ID.
            maps_service: Maps service.
            users_service: Users service.

        Returns:
            Enriched submission data.

        Raises:
            CustomHTTPException: If not found.
        """

        async def _get_user_coalesced_name(user_id: int) -> str:
            user = await users_service.get_user(user_id)
            if user:
                return user.coalesced_name or "Unknown User"
            return "Unknown User"

        try:
            return await maps_service.get_edit_submission(
                edit_id,
                get_creator_name=_get_user_coalesced_name,
            )

        except EditRequestNotFoundError:
            raise CustomHTTPException(
                detail=f"Edit request {edit_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from None

    @patch(
        "/{edit_id:int}/message",
        summary="Set Message ID",
        description="Associate a Discord message ID with an edit request.",
    )
    async def set_message_id_endpoint(
        self,
        edit_id: int,
        data: Annotated[MapEditSetMessageIdRequest, Body(title="Message ID")],
        maps_service: MapsService,
    ) -> Response:
        """Set verification queue message ID.

        Args:
            edit_id: Edit request ID.
            data: Message ID data.
            maps_service: Maps service.

        Returns:
            Empty 204 response.

        Raises:
            CustomHTTPException: If not found.
        """
        try:
            await maps_service.set_edit_message_id(edit_id, data.message_id)
            return Response(None, status_code=HTTP_204_NO_CONTENT)

        except EditRequestNotFoundError:
            raise CustomHTTPException(
                detail=f"Edit request {edit_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from None

    @put(
        "/{edit_id:int}/resolve",
        summary="Resolve Edit Request",
        description="Accept or reject a map edit request.",
    )
    async def resolve_edit_request_endpoint(
        self,
        request: Request,
        edit_id: int,
        data: Annotated[MapEditResolveRequest, Body(title="Resolve data")],
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        notifications_service: NotificationService,
        users_service: UserService,
    ) -> Response:
        """Resolve an edit request.

        Args:
            request: Request object.
            edit_id: Edit request ID.
            data: Resolution data.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            notifications_service: Notification service.
            users_service: Users service.

        Returns:
            Empty 204 response.

        Raises:
            CustomHTTPException: On errors.
        """
        try:
            await maps_service.resolve_edit_request(
                edit_id=edit_id,
                accepted=data.accepted,
                resolved_by=data.resolved_by,
                rejection_reason=data.rejection_reason,
                send_to_playtest=data.send_to_playtest,
                headers=request.headers,
                newsfeed_service=newsfeed_service,
                notification_service=notifications_service,
                user_service=users_service,
            )
            return Response(None, status_code=HTTP_204_NO_CONTENT)

        except EditRequestNotFoundError:
            raise CustomHTTPException(
                detail=f"Edit request {edit_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from None

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"Map {e.message} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @get(
        "/user/{user_id:int}",
        summary="Get User's Edit Requests",
        description="Get all edit requests submitted by a user.",
    )
    async def get_user_edit_requests_endpoint(
        self,
        user_id: int,
        maps_service: MapsService,
        include_resolved: bool = False,
    ) -> list[MapEditResponse]:
        """Get user's edit requests.

        Args:
            user_id: User ID.
            include_resolved: Whether to include resolved requests.
            maps_service: Maps service.

        Returns:
            List of edit requests.
        """
        return await maps_service.get_user_edit_requests(user_id, include_resolved)
