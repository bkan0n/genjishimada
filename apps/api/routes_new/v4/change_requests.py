"""V4 Change Requests routes."""

from __future__ import annotations

from typing import Annotated

from genjishimada_sdk.change_requests import (
    ChangeRequestCreateRequest,
    ChangeRequestResponse,
    StaleChangeRequestResponse,
)
from genjishimada_sdk.maps import OverwatchCode
from litestar import Controller, get, patch, post
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED

from repository.change_requests_repository import provide_change_requests_repository
from services.change_requests_service import ChangeRequestsService, provide_change_requests_service


class ChangeRequestsController(Controller):
    """Endpoints for map change requests."""

    tags = ["Change Requests"]
    path = "/change-requests"
    dependencies = {
        "change_requests_repo": Provide(provide_change_requests_repository),
        "change_requests_service": Provide(provide_change_requests_service),
    }

    @get(
        path="/permission",
        summary="Check Creator-Only Button Permission",
        description="Return whether the given `user_id` is included in the creator mentions for the thread and code.",
    )
    async def check_permission_endpoint(
        self,
        change_requests_service: ChangeRequestsService,
        thread_id: int,
        user_id: int,
        code: OverwatchCode,
    ) -> bool:
        """Check whether a user can see creator-only UI actions.

        Args:
            change_requests_service: Service dependency.
            thread_id: Discord thread ID associated with the change request.
            user_id: The user to check for permission.
            code: The Overwatch map code.

        Returns:
            True if the user is included in creator_mentions, else False.
        """
        return await change_requests_service.check_permission(thread_id, user_id, code)

    @post(
        path="/",
        summary="Create Change Request",
        description="Create a change request for a specific map code and discussion thread.",
    )
    async def create_change_request_endpoint(
        self,
        data: Annotated[ChangeRequestCreateRequest, Body(title="Change request data")],
        change_requests_service: ChangeRequestsService,
    ) -> Response[None]:
        """Create a new change request.

        Args:
            data: Change request creation payload.
            change_requests_service: Service dependency.

        Returns:
            Empty response with 201 status.
        """
        await change_requests_service.create_request(data)
        return Response(None, status_code=HTTP_201_CREATED)

    @patch(
        path="/{thread_id:int}/resolve",
        summary="Resolve Change Request",
        description="Mark the change request associated with the given thread as resolved.",
    )
    async def resolve_change_request_endpoint(
        self,
        thread_id: int,
        change_requests_service: ChangeRequestsService,
    ) -> Response[None]:
        """Resolve a change request by thread.

        Args:
            thread_id: Discord thread ID to resolve.
            change_requests_service: Service dependency.

        Returns:
            Empty response with 200 status.
        """
        await change_requests_service.resolve_request(thread_id)
        return Response(None, status_code=HTTP_200_OK)

    @get(
        path="/",
        summary="List Open Change Requests by Code",
        description="List all unresolved change requests for the specified map code, newest first.",
    )
    async def get_change_requests_endpoint(
        self,
        change_requests_service: ChangeRequestsService,
        code: OverwatchCode,
    ) -> list[ChangeRequestResponse]:
        """Get unresolved change requests for a map.

        Args:
            change_requests_service: Service dependency.
            code: The Overwatch map code.

        Returns:
            List of unresolved change requests.
        """
        return await change_requests_service.get_unresolved_requests(code)

    @get(
        path="/stale",
        summary="List Stale Change Requests",
        description="Return change requests older than two weeks that are neither alerted nor resolved.",
    )
    async def get_stale_change_requests_endpoint(
        self,
        change_requests_service: ChangeRequestsService,
    ) -> list[StaleChangeRequestResponse]:
        """Get stale change requests needing follow-up.

        Args:
            change_requests_service: Service dependency.

        Returns:
            List of stale change requests.
        """
        return await change_requests_service.get_stale_requests()

    @patch(
        path="/{thread_id:int}/alerted",
        summary="Mark Change Request as Alerted",
        description="Mark the change request associated with the given thread as having been alerted.",
    )
    async def update_alerted_change_request_endpoint(
        self,
        thread_id: int,
        change_requests_service: ChangeRequestsService,
    ) -> Response[None]:
        """Set a change request to alerted state.

        Args:
            thread_id: Discord thread ID to mark as alerted.
            change_requests_service: Service dependency.

        Returns:
            Empty response with 200 status.
        """
        await change_requests_service.mark_alerted(thread_id)
        return Response(None, status_code=HTTP_200_OK)
