"""V4 Completions routes."""

from __future__ import annotations

from logging import getLogger
from typing import Literal

from genjishimada_sdk.completions import (
    CompletionCreateRequest,
    CompletionModerateRequest,
    CompletionPatchRequest,
    CompletionResponse,
    CompletionSubmissionJobResponse,
    CompletionSubmissionResponse,
    CompletionVerificationUpdateRequest,
    PendingVerificationResponse,
    QualityUpdateRequest,
    SuspiciousCompletionCreateRequest,
    SuspiciousCompletionResponse,
    UpvoteCreateRequest,
    UpvoteSubmissionJobResponse,
)
from genjishimada_sdk.difficulties import DifficultyTop
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import OverwatchCode
from litestar import Controller, Request, Response, get, patch, post, put
from litestar.datastructures import State
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

from repository.completions_repository import provide_completions_repository
from repository.users_repository import provide_users_repository
from services.completions_service import CompletionsService, provide_completions_service
from services.exceptions.completions import (
    CompletionNotFoundError,
    DuplicateCompletionError,
    DuplicateQualityVoteError,
    DuplicateUpvoteError,
    DuplicateVerificationError,
    MapNotFoundError,
    SlowerThanPendingError,
)
from services.notifications_service import NotificationsService, provide_notifications_service
from services.users_service import UsersService, provide_users_service
from utilities.errors import CustomHTTPException

log = getLogger(__name__)


class CompletionsController(Controller):
    """Completions."""

    tags = ["Completions"]
    path = "/completions"
    dependencies = {
        "completions_repo": Provide(provide_completions_repository),
        "svc": Provide(provide_completions_service),
        "users": Provide(provide_users_service),
        "notifications": Provide(provide_notifications_service),
        "users_repo": Provide(provide_users_repository),
    }

    @get(
        path="/",
        summary="Get User Completions",
        description="Retrieve all verified completions for a given user, optionally filtered by difficulty.",
        opt={"required_scopes": {"completions:read"}},
    )
    async def get_completions_for_user(
        self,
        svc: CompletionsService,
        user_id: int,
        difficulty: DifficultyTop | None = None,
        page_size: int = 10,
        page_number: int = 1,
    ) -> Response[list[CompletionResponse]]:
        """Get completions for a specific user."""
        resp = await svc.get_completions_for_user(user_id, difficulty, page_size, page_number)
        return Response(resp)

    @get(
        path="/world-records",
        summary="Get User World Records",
        description="Retrieve all verified World Records for a given user.",
        opt={"required_scopes": {"completions:read"}},
    )
    async def get_world_records_per_user(
        self,
        svc: CompletionsService,
        user_id: int,
    ) -> list[CompletionResponse]:
        """Get completions for a specific user."""
        return await svc.get_world_records_per_user(user_id)

    @post(path="/", summary="Submit Completion", description="Submit a new completion record and publish an event.")
    async def submit_completion(
        self,
        svc: CompletionsService,
        request: Request,
        data: CompletionCreateRequest,
        notifications: NotificationsService,
        users: UsersService,
    ) -> CompletionSubmissionJobResponse:
        """Submit a new completion."""
        try:
            resp = await svc.submit_completion(data, request, notifications, users)
            return resp
        except MapNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateCompletionError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
        except SlowerThanPendingError as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e

    @patch(
        path="/{record_id:int}",
        summary="Edit Completion",
        description="Apply partial updates to a completion record.",
        include_in_schema=False,
    )
    async def edit_completion(
        self,
        svc: CompletionsService,
        state: State,
        record_id: int,
        data: CompletionPatchRequest,
    ) -> None:
        """Patch an existing completion."""
        try:
            return await svc.edit_completion(state, record_id, data)
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateCompletionError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e

    @get(
        path="/{record_id:int}/submission",
        summary="Get Completion Submission",
        description=(
            "Retrieve enriched submission details for a specific completion, "
            "including ranks, medals, and display names."
        ),
    )
    async def get_completion_submission(
        self,
        svc: CompletionsService,
        record_id: int,
    ) -> CompletionSubmissionResponse:
        """Get a detailed view of a completion submission."""
        try:
            return await svc.get_completion_submission(record_id)
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e

    @get(
        path="/pending",
        summary="Get Pending Verifications",
        description="Retrieve all completions that are awaiting verification.",
    )
    async def get_pending_verifications(
        self,
        svc: CompletionsService,
    ) -> list[PendingVerificationResponse]:
        """Get completions waiting for verification."""
        return await svc.get_pending_verifications()

    @put(
        path="/{record_id:int}/verification",
        summary="Verify Completion",
        description="Update the verification status of a completion and publish an event.",
    )
    async def verify_completion(
        self,
        svc: CompletionsService,
        request: Request,
        notifications: NotificationsService,
        record_id: int,
        data: CompletionVerificationUpdateRequest,
    ) -> JobStatusResponse:
        """Verify or reject a completion."""
        try:
            return await svc.verify_completion(request, record_id, data, notifications=notifications)
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateVerificationError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e

    @get(
        path="/{code:str}",
        summary="Get Map Leaderboard",
        description="Retrieve the leaderboard for a given map, including ranks and medals.",
        opt={"required_scopes": {"completions:read"}},
    )
    async def get_completions_leaderboard(
        self,
        svc: CompletionsService,
        code: OverwatchCode,
        page_size: int = 10,
        page_number: int = 1,
    ) -> list[CompletionResponse]:
        """Get the leaderboard for a map."""
        return await svc.get_completions_leaderboard(code, page_number, page_size)

    @get(
        path="/suspicious",
        summary="Get Suspicious Flags",
        description="Retrieve suspicious flags associated with a user's completions.",
    )
    async def get_suspicious_flags(
        self,
        svc: CompletionsService,
        user_id: int,
    ) -> list[SuspiciousCompletionResponse]:
        """Get suspicious flags for a user."""
        return await svc.get_suspicious_flags(user_id)

    @post(
        path="/suspicious", summary="Set Suspicious Flag", description="Insert a new suspicious flag for a completion."
    )
    async def set_suspicious_flags(
        self,
        svc: CompletionsService,
        data: SuspiciousCompletionCreateRequest,
    ) -> None:
        """Add a suspicious flag to a completion."""
        if not data.message_id and not data.verification_id:
            raise CustomHTTPException(
                detail="One of message_id or verification_id must be used.", status_code=HTTP_400_BAD_REQUEST
            )
        return await svc.set_suspicious_flags(data)

    @post(
        path="/upvoting",
        summary="Upvote Submission",
        description="Upvote a completion submission. Returns the updated count.",
    )
    async def upvote_submission(
        self,
        svc: CompletionsService,
        request: Request,
        data: UpvoteCreateRequest,
    ) -> UpvoteSubmissionJobResponse:
        """Upvote a completion submission."""
        try:
            return await svc.upvote_submission(request, data)
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateUpvoteError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e

    @get(
        path="/all",
        summary="Get All Completions",
        description="Get all completions that are verified sorted by most recent.",
    )
    async def get_all_completions(
        self,
        svc: CompletionsService,
        page_size: int = 10,
        page_number: int = 1,
    ) -> list[CompletionResponse]:
        """Get all completions that are verified sorted by most recent."""
        return await svc.get_all_completions(page_size, page_number)

    @get(path="/{code:str}/wr-xp-check", include_in_schema=False)
    async def check_for_previous_world_record_xp(
        self,
        svc: CompletionsService,
        code: OverwatchCode,
        user_id: int,
    ) -> bool:
        """Check if a record submitted by this user has ever received World Record XP."""
        return await svc.check_for_previous_world_record(code, user_id)

    @get(
        path="/moderation/records",
        summary="Get Records with Filters",
        description="Fetch completion records with optional filters for moderation purposes.",
    )
    async def get_records_filtered(  # noqa: PLR0913
        self,
        svc: CompletionsService,
        code: OverwatchCode | None = None,
        user_id: int | None = None,
        verification_status: Literal["Verified", "Unverified", "All"] = "All",
        latest_only: bool = True,
        page_size: int = 10,
        page_number: int = 1,
    ) -> list[CompletionResponse]:
        """Get filtered records for moderation."""
        return await svc.get_records_filtered(
            code=code,
            user_id=user_id,
            verification_status=verification_status,
            latest_only=latest_only,
            page_size=page_size,
            page_number=page_number,
        )

    @put(
        path="/{record_id:int}/moderate",
        summary="Moderate Completion",
        description="Moderate a completion record (change time, verification status, suspicious flag).",
    )
    async def moderate_completion(
        self,
        svc: CompletionsService,
        notifications: NotificationsService,
        request: Request,
        record_id: int,
        data: CompletionModerateRequest,
    ) -> None:
        """Moderate a completion record."""
        try:
            return await svc.moderate_completion(record_id, data, notifications, request.headers)
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateCompletionError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e

    @get(
        path="/{code:str}/legacy",
        summary="Get Legacy Completions Per Map",
        description="Get all legacy completions for a particular map code.",
    )
    async def get_legacy_completions_per_map(
        self,
        svc: CompletionsService,
        code: OverwatchCode,
        page_number: int = 1,
        page_size: int = 10,
    ) -> list[CompletionResponse]:
        """Get the legacy completions for a map code."""
        return await svc.get_legacy_completions_per_map(code, page_number, page_size)

    @post(
        path="/{code:str}/quality",
        summary="Set Quality Vote",
        description="Set the quality vote for a user for a map code.",
    )
    async def set_quality_vote_for_map_code(
        self,
        svc: CompletionsService,
        code: OverwatchCode,
        data: QualityUpdateRequest,
    ) -> None:
        """Set the quality vote for a map code for a user."""
        try:
            return await svc.set_quality_vote_for_map_code(code, data.user_id, data.quality)
        except MapNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateQualityVoteError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
        except CompletionNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e

    @get(path="/upvoting/{message_id:int}")
    async def get_upvotes_from_message_id(self, svc: CompletionsService, message_id: int) -> int:
        """Get upvote count from a message id."""
        return await svc.get_upvotes_from_message_id(message_id)
