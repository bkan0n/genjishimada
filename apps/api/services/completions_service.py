"""Completions service for business logic and orchestration."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

import aiohttp
import msgspec
import rapidfuzz
import sentry_sdk
from asyncpg import Connection, Pool
from genjishimada_sdk.completions import (
    CompletionCreatedEvent,
    CompletionCreateRequest,
    CompletionModerateRequest,
    CompletionPatchRequest,
    CompletionResponse,
    CompletionSubmissionJobResponse,
    CompletionSubmissionResponse,
    CompletionVerificationUpdateRequest,
    FailedAutoverifyEvent,
    OcrResponse,
    PendingVerificationResponse,
    SuspiciousCompletionCreateRequest,
    SuspiciousCompletionResponse,
    UpvoteCreateRequest,
    UpvoteSubmissionJobResponse,
    UpvoteUpdateEvent,
    VerificationChangedEvent,
    VerificationMessageDeleteEvent,
)
from genjishimada_sdk.difficulties import DifficultyTop
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import OverwatchCode
from genjishimada_sdk.notifications import NotificationCreateRequest, NotificationEventType
from litestar import Request
from litestar.datastructures import Headers, State
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from repository.autocomplete_repository import AutocompleteRepository
from repository.completions_repository import CompletionsRepository
from repository.exceptions import (
    CheckConstraintViolationError,
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)
from utilities.errors import CustomHTTPException

from .base import BaseService
from .users import UserService

if TYPE_CHECKING:
    from di.notifications import NotificationService

log = getLogger(__name__)


class CompletionsService(BaseService):
    """Service for completions domain."""

    def __init__(self, pool: Pool, state: State, completions_repo: CompletionsRepository) -> None:
        """Initialize completions service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            completions_repo: Completions repository.
        """
        super().__init__(pool, state)
        self._completions_repo = completions_repo

    async def get_completions_for_user(
        self,
        user_id: int,
        difficulty: DifficultyTop | None = None,
        page_size: int = 10,
        page_number: int = 1,
    ) -> list[CompletionResponse]:
        """Retrieve verified completions for a user."""
        rows = await self._completions_repo.fetch_user_completions(
            user_id=user_id,
            difficulty=difficulty,
            page_size=page_size,
            page_number=page_number,
        )
        return msgspec.convert(rows, list[CompletionResponse])

    async def _attempt_auto_verify(
        self,
        request: Request,
        autocomplete: AutocompleteService,
        users: UserService,
        completion_id: int,
        data: CompletionCreateRequest,
    ) -> bool:
        """Attempt to auto-verify a completion using OCR.

        Returns:
            True if auto-verification succeeded, False otherwise.
        """
        idempotency_key = f"completion:submission:{data.user_id}:{completion_id}"

        try:
            hostname = "genjishimada-ocr" if os.getenv("APP_ENVIRONMENT") == "production" else "genjishimada-ocr-dev"
            try:
                async with (
                    aiohttp.ClientSession() as session,
                    session.post(f"http://{hostname}:8000/extract", json={"image_url": data.screenshot}) as resp,
                ):
                    resp.raise_for_status()
                    raw_ocr_data = await resp.read()
                    ocr_data = msgspec.json.decode(raw_ocr_data, type=OcrResponse)

                extracted = ocr_data.extracted

                user_name_response = await users.fetch_all_user_names(data.user_id)
                user_names = [x.upper() for x in user_name_response]
                name_match = False
                if extracted.name and user_names:
                    best_match = rapidfuzz.process.extractOne(
                        extracted.name,
                        user_names,
                        scorer=rapidfuzz.fuzz.ratio,
                        score_cutoff=60,
                    )

                    if best_match:
                        matched_name, score, _ = best_match
                        log.debug(f"Name fuzzy match: '{extracted.name}' → '{matched_name}' (score: {score})")
                        name_match = True
                    else:
                        log.debug(f"No name match found for '{extracted.name}' against {user_names}")

                extracted_code_cleaned = await autocomplete.transform_map_codes(extracted.code or "")
                if extracted_code_cleaned:
                    extracted_code_cleaned = extracted_code_cleaned.replace('"', "")

                code_match = data.code == extracted_code_cleaned
                time_match = data.time == extracted.time
                user_match = name_match

                log.debug(f"extracted: {extracted}")
                log.debug(f"data: {data}")
                log.debug(f"extracted_code_cleaned: {extracted_code_cleaned}")
                log.debug(f"code_match: {code_match} ({data.code=} vs {extracted_code_cleaned=})")
                log.debug(f"time_match: {time_match} ({data.time=} vs {extracted.time=})")
                log.debug(f"user_match: {user_match} ({name_match=})")

                if code_match and time_match and user_match:
                    verification_data = CompletionVerificationUpdateRequest(
                        verified_by=969632729643753482,
                        verified=True,
                        reason="Auto Verified by Genji Shimada.",
                    )
                    await self.verify_completion_with_pool(request, completion_id, verification_data)
                    return True
            except aiohttp.ClientConnectorDNSError:
                log.warning("OCR service DNS error, falling back to manual verification")
                await self.publish_message(
                    routing_key="api.completion.submission",
                    data=CompletionCreatedEvent(completion_id),
                    headers=request.headers,
                    idempotency_key=idempotency_key,
                )
                return False

            # Autoverification failed validation, send failure details and fall back to manual
            await self.publish_message(
                routing_key="api.completion.autoverification.failed",
                data=FailedAutoverifyEvent(
                    submitted_code=data.code,
                    submitted_time=data.time,
                    user_id=data.user_id,
                    extracted=extracted,
                    code_match=code_match,
                    time_match=time_match,
                    user_match=user_match,
                    extracted_code_cleaned=extracted_code_cleaned,
                    extracted_time=extracted.time,
                    usernames=user_names,
                ),
                headers=request.headers,
                idempotency_key=None,
            )
            await self.publish_message(
                routing_key="api.completion.submission",
                data=CompletionCreatedEvent(completion_id),
                headers=request.headers,
                idempotency_key=idempotency_key,
            )
            return False

        except Exception as e:
            log.exception(
                "[!] Autoverification failed with unexpected error for completion_id=%s: %s",
                completion_id,
                e,
            )
            sentry_sdk.capture_exception(e)

            await self.publish_message(
                routing_key="api.completion.submission",
                data=CompletionCreatedEvent(completion_id),
                headers=request.headers,
                idempotency_key=idempotency_key,
            )
            return False

    async def submit_completion(
        self, data: CompletionCreateRequest, request: Request, autocomplete: AutocompleteRepository
    ) -> CompletionSubmissionJobResponse:
        """Submit a new completion record and publish an event."""
        map_exists = await self._completions_repo.check_map_exists(data.code)
        if not map_exists:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="This map code does not exist or has been archived.",
            )

        try:
            completion_id, verification_id_to_delete = await self._completions_repo.submit_completion(
                user_id=data.user_id,
                code=data.code,
                time=data.time,
                screenshot=data.screenshot,
                video=data.video,
            )
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="You already have a completion for this map.",
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid user or map ID.",
            ) from e
        except CheckConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

        if verification_id_to_delete:
            delete_event = VerificationMessageDeleteEvent(verification_id_to_delete)
            await self.publish_message(
                routing_key="api.completion.verification.delete",
                data=delete_event,
                headers=request.headers,
                idempotency_key=None,
            )

        if not completion_id:
            raise ValueError("Some how completion ID is null?")

        suspicious_flags = await self.get_suspicious_flags(data.user_id)

        if not (data.video or suspicious_flags):
            try:
                auto_verified = await asyncio.wait_for(
                    self._attempt_auto_verify(
                        request=request,
                        autocomplete=autocomplete,
                        users=users,
                        completion_id=completion_id,
                        data=data,
                    ),
                    timeout=5.0,
                )
                if auto_verified:
                    return CompletionSubmissionJobResponse(None, completion_id)
            except asyncio.TimeoutError:
                log.warning(f"Auto-verification timed out for completion {completion_id}, falling back to manual")

        idempotency_key = f"completion:submission:{data.user_id}:{completion_id}"
        job_status = await self.publish_message(
            routing_key="api.completion.submission",
            data=CompletionCreatedEvent(completion_id),
            headers=request.headers,
            idempotency_key=idempotency_key,
        )
        return CompletionSubmissionJobResponse(job_status, completion_id)

    def _build_patch_dict(self, patch: CompletionPatchRequest) -> dict[str, Any]:
        """Build patch dict excluding UNSET fields."""
        patch_data: dict[str, Any] = {}
        for field_name, value in msgspec.structs.asdict(patch).items():
            if value is not msgspec.UNSET:
                patch_data[field_name] = value
        return patch_data

    async def _run_repo_write(
        self,
        operation: Callable[[], Awaitable[None]],
        *,
        unique_message: str,
        fk_message: str,
    ) -> None:
        """Run a repository write and translate constraint errors."""
        try:
            await operation()
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=unique_message,
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=fk_message,
            ) from e
        except CheckConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    async def edit_completion(self, state: State, record_id: int, data: CompletionPatchRequest) -> None:
        """Apply partial updates to a completion record."""
        _ = state
        patch_data = self._build_patch_dict(data)
        try:
            await self._completions_repo.edit_completion(record_id, patch_data)
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="This completion already exists.",
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid user or map ID.",
            ) from e
        except CheckConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    async def check_for_previous_world_record(self, code: OverwatchCode, user_id: int) -> bool:
        """Check if a record submitted by this user has ever received World Record XP."""
        return await self._completions_repo.check_previous_world_record_xp(code, user_id)

    async def get_completion_submission(self, record_id: int) -> CompletionSubmissionResponse:
        """Retrieve detailed submission info for a completion."""
        row = await self._completions_repo.fetch_completion_submission(record_id)
        return msgspec.convert(row, CompletionSubmissionResponse)

    async def get_pending_verifications(self) -> list[PendingVerificationResponse]:
        """Retrieve completions awaiting verification."""
        rows = await self._completions_repo.fetch_pending_verifications()
        return msgspec.convert(rows, list[PendingVerificationResponse])

    async def verify_completion(
        self,
        request: Request,
        record_id: int,
        data: CompletionVerificationUpdateRequest,
        *,
        conn: Connection | None = None,
    ) -> JobStatusResponse:
        """Update verification status for a completion and publish an event."""
        try:
            await self._completions_repo.update_verification(
                record_id,
                data.verified,
                data.verified_by,
                data.reason,
                conn=conn,
            )
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Verification record already exists.",
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid completion or user ID.",
            ) from e
        except CheckConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

        message_data = VerificationChangedEvent(
            completion_id=record_id,
            verified=data.verified,
            verified_by=data.verified_by,
            reason=data.reason,
        )
        idempotency_key = f"completion:verify:{record_id}"
        job_status = await self.publish_message(
            routing_key="api.completion.verification",
            data=message_data,
            headers=request.headers,
            idempotency_key=idempotency_key,
        )
        return job_status

    async def verify_completion_with_pool(
        self,
        request: Request,
        record_id: int,
        data: CompletionVerificationUpdateRequest,
    ) -> JobStatusResponse:
        """Verify completion using pool connection."""
        async with self._pool.acquire() as conn:
            return await self.verify_completion(request, record_id, data, conn=cast(Connection, conn))

    async def get_completions_leaderboard(
        self, code: str, page_number: int, page_size: int
    ) -> list[CompletionResponse]:
        """Retrieve the leaderboard for a map."""
        rows = await self._completions_repo.fetch_map_leaderboard(
            code=code,
            page_size=page_size,
            page_number=page_number,
        )
        return msgspec.convert(rows, list[CompletionResponse])

    async def get_world_records_per_user(self, user_id: int) -> list[CompletionResponse]:
        """Get all world records for a specific user."""
        rows = await self._completions_repo.fetch_world_records_per_user(user_id)
        return msgspec.convert(rows, list[CompletionResponse])

    async def get_legacy_completions_per_map(
        self,
        code: OverwatchCode,
        page_number: int,
        page_size: int,
    ) -> list[CompletionResponse]:
        """Get legacy completions for a map code."""
        rows = await self._completions_repo.fetch_legacy_completions(code, page_size, page_number)
        return msgspec.convert(rows, list[CompletionResponse])

    async def get_suspicious_flags(self, user_id: int) -> list[SuspiciousCompletionResponse]:
        """Retrieve suspicious flags associated with a user."""
        rows = await self._completions_repo.fetch_suspicious_flags(user_id)
        return msgspec.convert(rows, list[SuspiciousCompletionResponse])

    async def set_suspicious_flags(self, data: SuspiciousCompletionCreateRequest) -> None:
        """Insert a suspicious flag for a completion."""
        try:
            await self._completions_repo.insert_suspicious_flag(
                message_id=data.message_id,
                verification_id=data.verification_id,
                context=data.context,
                flag_type=data.flag_type,
                flagged_by=data.flagged_by,
            )
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="This flag already exists.",
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid completion or user ID.",
            ) from e

    async def get_upvotes_from_message_id(self, message_id: int) -> int:
        """Get the upvotes for a particular completion by message_id."""
        return await self._completions_repo.fetch_upvote_count(message_id)

    async def upvote_submission(self, request: Request, data: UpvoteCreateRequest) -> UpvoteSubmissionJobResponse:
        """Upvote a completion submission."""
        try:
            count = await self._completions_repo.insert_upvote(data.user_id, data.message_id)
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                detail="User has already upvoted this completion.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                detail="Invalid completion or user ID.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e
        upvote_channel_amount_breakpoint = 10
        if count is None:
            raise CustomHTTPException(
                detail="User has already upvoted this completion.", status_code=HTTP_400_BAD_REQUEST
            )
        job_status = None
        if count != 0 and count % upvote_channel_amount_breakpoint == 0:
            message_data = UpvoteUpdateEvent(
                data.user_id,
                data.message_id,
            )
            job_status = await self.publish_message(
                routing_key="api.completion.upvote",
                data=message_data,
                headers=request.headers,
                idempotency_key=None,
            )
        return UpvoteSubmissionJobResponse(job_status, count)

    async def get_all_completions(self, page_size: int, page_number: int) -> list[CompletionResponse]:
        """Get all completions from most recent."""
        rows = await self._completions_repo.fetch_all_completions(page_size, page_number)
        return msgspec.convert(rows, list[CompletionResponse])

    async def set_quality_vote_for_map_code(self, code: OverwatchCode, user_id: int, quality: int) -> None:
        """Set the quality vote for a map code per user."""
        try:
            await self._completions_repo.upsert_quality_vote(code, user_id, quality)
        except UniqueConstraintViolationError as e:
            raise CustomHTTPException(
                detail="Quality vote already exists.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e
        except ForeignKeyViolationError as e:
            raise CustomHTTPException(
                detail="Invalid user or map ID.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e
        except CheckConstraintViolationError as e:
            raise CustomHTTPException(
                detail=str(e),
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    async def get_records_filtered(  # noqa: PLR0913
        self,
        code: OverwatchCode | None = None,
        user_id: int | None = None,
        verification_status: str = "All",
        latest_only: bool = True,
        page_size: int = 10,
        page_number: int = 1,
    ) -> list[CompletionResponse]:
        """Fetch records with filters for moderation."""
        rows = await self._completions_repo.fetch_records_filtered(
            code=code,
            user_id=user_id,
            verification_status=verification_status,
            latest_only=latest_only,
            page_size=page_size,
            page_number=page_number,
        )
        return msgspec.convert(rows, list[CompletionResponse])

    async def moderate_completion(  # noqa: PLR0912
        self,
        completion_id: int,
        data: CompletionModerateRequest,
        notification_service: NotificationService | None = None,
        headers: Headers | None = None,
    ) -> None:
        """Moderate a completion record."""
        completion_info = await self._completions_repo.fetch_completion_for_moderation(completion_id)
        if not completion_info:
            raise CustomHTTPException(
                detail="Completion not found",
                status_code=HTTP_400_BAD_REQUEST,
            )

        user_id = completion_info["user_id"]
        map_code = completion_info["code"]
        old_time = completion_info["old_time"]
        old_verified = completion_info["old_verified"]

        notification_messages: list[str] = []

        # Handle time change
        if data.time is not msgspec.UNSET:
            if data.time_change_reason is msgspec.UNSET:
                raise CustomHTTPException(
                    detail="time_change_reason is required when changing time",
                    status_code=HTTP_400_BAD_REQUEST,
                )
            new_time = cast(float, data.time)
            await self._run_repo_write(
                lambda: self._completions_repo.update_completion_time(completion_id, new_time),
                unique_message="This completion already exists.",
                fk_message="Invalid completion or user ID.",
            )
            notification_messages.append(
                f"Your completion time on **{map_code}** was changed from **{old_time}s** to **{new_time}s**.\n"
                f"Reason: {data.time_change_reason}"
            )

        # Handle verification change
        if data.verified is not msgspec.UNSET:
            verified = cast(bool, data.verified)
            await self._run_repo_write(
                lambda: self._completions_repo.update_completion_verified(completion_id, verified),
                unique_message="This completion already exists.",
                fk_message="Invalid completion or user ID.",
            )

            if verified != old_verified:
                if verified:
                    notification_messages.append(f"Your completion on **{map_code}** has been verified by a moderator.")
                else:
                    reason_msg = f"\nReason: {data.verification_reason}" if data.verification_reason else ""
                    notification_messages.append(
                        f"Your completion on **{map_code}** has been unverified by a moderator.{reason_msg}"
                    )

        # Handle suspicious flag
        if data.mark_suspicious:
            if data.suspicious_context is msgspec.UNSET or data.suspicious_flag_type is msgspec.UNSET:
                raise CustomHTTPException(
                    detail="suspicious_context and suspicious_flag_type are required when marking as suspicious",
                    status_code=HTTP_400_BAD_REQUEST,
                )
            suspicious_context = cast(str, data.suspicious_context)
            suspicious_flag_type = cast(str, data.suspicious_flag_type)
            existing = await self._completions_repo.check_suspicious_flag_exists(completion_id)
            if not existing:
                await self._run_repo_write(
                    lambda: self._completions_repo.insert_suspicious_flag_by_completion_id(
                        completion_id,
                        suspicious_context,
                        suspicious_flag_type,
                        data.moderated_by,
                    ),
                    unique_message="This flag already exists.",
                    fk_message="Invalid completion or user ID.",
                )
                notification_messages.append(
                    f"Your completion on **{map_code}** has been flagged as suspicious ({suspicious_flag_type}).\n"
                    f"Context: {suspicious_context}"
                )

        if data.unmark_suspicious:
            deleted_count = await self._completions_repo.delete_suspicious_flag(completion_id)
            if deleted_count > 0:
                notification_messages.append(
                    f"The suspicious flag on your completion for **{map_code}** has been removed."
                )

        # Send notification if any changes were made
        if notification_messages and notification_service is not None and headers is not None:
            notification_body = "\n\n".join(notification_messages)

            notification_data = NotificationCreateRequest(
                user_id=user_id,
                event_type=NotificationEventType.RECORD_EDITED,  # type: ignore
                title=f"Completion Updated - {map_code}",
                body=notification_body,
                discord_message=notification_body,
                metadata={"map_code": map_code, "completion_id": completion_id},
            )

            await notification_service.create_and_dispatch(notification_data, headers)


async def provide_completions_service(
    state: State,
    completions_repo: CompletionsRepository,
) -> CompletionsService:
    """Litestar DI provider for CompletionsService."""
    return CompletionsService(state.db_pool, state, completions_repo)
