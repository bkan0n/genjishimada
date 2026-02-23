"""Completions service for business logic and orchestration."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

import aiohttp
import msgspec
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
    DashboardCompletionResponse,
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
from genjishimada_sdk.difficulties import DifficultyTop, convert_extended_difficulty_to_top_level
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import OverwatchCode
from genjishimada_sdk.notifications import NotificationCreateRequest, NotificationEventType
from litestar import Request
from litestar.datastructures import Headers, State

from events.schemas import OcrVerificationRequestedEvent
from repository.completions_repository import CompletionsRepository
from repository.exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)
from repository.lootbox_repository import LootboxRepository
from repository.store_repository import StoreRepository
from repository.users_repository import UsersRepository
from services.exceptions.completions import (
    CompletionNotFoundError,
    DuplicateCompletionError,
    DuplicateFlagError,
    DuplicateQualityVoteError,
    DuplicateUpvoteError,
    DuplicateVerificationError,
    MapNotFoundError,
    SlowerThanPendingError,
)

from .base import BaseService
from .store_service import StoreService
from .users_service import UsersService

if TYPE_CHECKING:
    from .notifications_service import NotificationsService

log = getLogger(__name__)

BOT_USER_ID = 969632729643753482


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

    @staticmethod
    def _compute_medal(time_value: float, thresholds: dict | None) -> str | None:
        if not thresholds:
            return None
        if thresholds.get("gold") and time_value <= float(thresholds["gold"]):
            return "Gold"
        if thresholds.get("silver") and time_value <= float(thresholds["silver"]):
            return "Silver"
        if thresholds.get("bronze") and time_value <= float(thresholds["bronze"]):
            return "Bronze"
        return None

    async def _update_quest_progress_for_completion(
        self,
        *,
        user_id: int,
        map_code: str,
        time: float,
        notifications: NotificationsService | None,
        headers: Headers,
    ) -> None:
        map_meta = await self._completions_repo.fetch_map_metadata_by_code(map_code)
        if not map_meta:
            return

        store_repo = StoreRepository(self._pool)
        lootbox_repo = LootboxRepository(self._pool)
        store_service = StoreService(self._pool, self._state, store_repo, lootbox_repo)
        medal_thresholds = await store_repo.get_medal_thresholds(map_meta["map_id"])
        medal = self._compute_medal(float(time), medal_thresholds)

        completed_quests = await store_service.update_quest_progress(
            user_id=user_id,
            event_type="completion",
            event_data={
                "map_id": map_meta["map_id"],
                "difficulty": convert_extended_difficulty_to_top_level(map_meta["difficulty"]),
                "category": map_meta["category"],
                "time": float(time),
                "medal": medal,
            },
        )

        if notifications:
            for quest in completed_quests:
                requirements = quest.get("requirements", {})
                rival_user_id = requirements.get("rival_user_id")
                rival_display_name = None
                completer_display_name = None

                if rival_user_id:
                    users_repo = UsersRepository(self._pool)
                    rival_user = await users_repo.fetch_user(rival_user_id)
                    rival_display_name = rival_user["coalesced_name"] if rival_user else "Unknown User"
                    completer_user = await users_repo.fetch_user(user_id)
                    completer_display_name = completer_user["coalesced_name"] if completer_user else "Unknown User"

                metadata = {
                    "quest_id": quest.get("quest_id"),
                    "progress_id": quest.get("progress_id"),
                    "quest_name": quest["name"],
                    "quest_difficulty": quest.get("difficulty"),
                    "coin_reward": quest.get("coin_reward"),
                    "xp_reward": quest.get("xp_reward"),
                    "rival_user_id": rival_user_id,
                    "rival_display_name": rival_display_name,
                }

                await notifications.create_and_dispatch(
                    data=NotificationCreateRequest(
                        user_id=user_id,
                        event_type=NotificationEventType.QUEST_COMPLETE,  # type: ignore
                        title="Quest Completed!",
                        body=(
                            f"You completed '{quest['name']}' and earned "
                            f"{quest.get('coin_reward', 0)} coins + {quest.get('xp_reward', 0)} XP."
                        ),
                        metadata=metadata,
                    ),
                    headers=headers,
                )

                if rival_user_id:
                    await notifications.create_and_dispatch(
                        data=NotificationCreateRequest(
                            user_id=rival_user_id,
                            event_type=NotificationEventType.QUEST_RIVAL_MENTION,  # type: ignore
                            title="Rival Quest Challenge",
                            body=f"{completer_display_name} completed a rival quest against you!",
                            discord_message=f"{completer_display_name} completed a rival quest against you!",
                            metadata={
                                "quest_name": quest["name"],
                                "quest_difficulty": quest.get("difficulty"),
                                "completer_user_id": user_id,
                                "completer_display_name": completer_display_name,
                            },
                        ),
                        headers=headers,
                    )

    async def _revert_quest_progress_for_completion(
        self,
        *,
        user_id: int,
        map_code: str,
        time: float,
    ) -> None:
        map_meta = await self._completions_repo.fetch_map_metadata_by_code(map_code)
        if not map_meta:
            return

        store_repo = StoreRepository(self._pool)
        lootbox_repo = LootboxRepository(self._pool)
        store_service = StoreService(self._pool, self._state, store_repo, lootbox_repo)
        remaining_times = await self._completions_repo.fetch_verified_times_for_user_map(
            user_id,
            map_meta["map_id"],
        )
        medal_thresholds = await store_repo.get_medal_thresholds(map_meta["map_id"])
        remaining_medals: list[str] = []
        if medal_thresholds:
            for remaining_time in remaining_times:
                medal = self._compute_medal(float(remaining_time), medal_thresholds)
                if medal:
                    remaining_medals.append(medal)

        await store_service.revert_quest_progress(
            user_id=user_id,
            event_type="completion",
            event_data={
                "map_id": map_meta["map_id"],
                "difficulty": convert_extended_difficulty_to_top_level(map_meta["difficulty"]),
                "category": map_meta["category"],
                "time": float(time),
            },
            remaining_times=remaining_times,
            remaining_medals=remaining_medals,
        )

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

    async def attempt_auto_verify_async(  # noqa: PLR0913
        self,
        completion_id: int,
        user_id: int,
        code: str,
        time: float,
        screenshot: str,
        users: UsersService,
        notifications: NotificationsService | None = None,
    ) -> None:
        """Attempt to auto-verify a completion using OCR.

        Runs asynchronously in response to completion.ocr.requested event.
        Always falls back to manual verification on any failure.

        Args:
            completion_id: Completion record ID.
            user_id: User who submitted the completion.
            code: Map code.
            time: Completion time.
            screenshot: Screenshot URL.
            users: Users service for fetching user names.
            notifications: Notifications service for sending failure notifications.
        """
        idempotency_key = f"completion:submission:{user_id}:{completion_id}"

        try:
            hostname = "genjishimada-ocr" if os.getenv("APP_ENVIRONMENT") == "production" else "genjishimada-ocr-dev"
            user_name_response = await users.fetch_all_user_names(user_id)
            user_names = [x.upper() for x in user_name_response]

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    f"http://{hostname}:8000/extract",
                    json={
                        "image_url": screenshot,
                        "code": code,
                        "time": time,
                        "names": user_names,
                    },
                ) as resp,
            ):
                resp.raise_for_status()
                raw_ocr_data = await resp.read()
                ocr_data = msgspec.json.decode(raw_ocr_data, type=OcrResponse)

            extracted = ocr_data.extracted

            code_match = code == extracted.code
            time_match = time == extracted.time
            user_match = extracted.name in user_names

            if code_match and time_match and user_match:
                verification_data = CompletionVerificationUpdateRequest(
                    verified_by=BOT_USER_ID,
                    verified=True,
                    reason="Auto Verified by Genji Shimada.",
                )
                await self.verify_completion_with_pool(
                    None, completion_id, verification_data, notifications=notifications
                )
                return

            await self.publish_message(
                routing_key="api.completion.autoverification.failed",
                data=FailedAutoverifyEvent(
                    submitted_code=code,
                    submitted_time=time,
                    submitted_user_names=user_names,
                    user_id=user_id,
                    extracted=extracted,
                    code_match=code_match,
                    time_match=time_match,
                    user_match=user_match,
                    screenshot=screenshot,
                ),
                headers=Headers(),
                idempotency_key=None,
            )
            await self.publish_message(
                routing_key="api.completion.submission",
                data=CompletionCreatedEvent(completion_id),
                headers=Headers(),
                idempotency_key=idempotency_key,
            )

            if notifications:
                await notifications.create_and_dispatch(
                    data=NotificationCreateRequest(
                        user_id=user_id,
                        event_type=NotificationEventType.AUTO_VERIFY_FAILED,  # type: ignore
                        title="Auto-Verification Failed",
                        body=(
                            f"Auto-verification failed for your completion on {code}. "
                            "Your submission is now awaiting manual verification."
                        ),
                        metadata={"completion_id": completion_id, "map_code": code},
                    ),
                    headers=Headers(),
                )

        except Exception as e:
            log.exception(
                "OCR auto-verification failed for completion_id=%s: %s",
                completion_id,
                e,
            )
            sentry_sdk.capture_exception(e)

            await self.publish_message(
                routing_key="api.completion.submission",
                data=CompletionCreatedEvent(completion_id),
                headers=Headers(),
                idempotency_key=idempotency_key,
            )

            if notifications:
                await notifications.create_and_dispatch(
                    data=NotificationCreateRequest(
                        user_id=user_id,
                        event_type=NotificationEventType.AUTO_VERIFY_FAILED,  # type: ignore
                        title="Auto-Verification Failed",
                        body=(
                            f"Auto-verification encountered an error for your completion on {code}. "
                            "Your submission is now awaiting manual verification."
                        ),
                        metadata={"completion_id": completion_id, "map_code": code},
                    ),
                    headers=Headers(),
                )

    async def submit_completion(
        self, data: CompletionCreateRequest, request: Request, notifications: NotificationsService, users: UsersService
    ) -> CompletionSubmissionJobResponse:
        """Submit a new completion record and publish an event.

        Args:
            data: Completion submission data.
            request: HTTP request (for headers).
            notifications: notifications service.
            users: Users service for name fetching.

        Returns:
            Job response with completion ID.

        Raises:
            MapNotFoundError: If map code doesn't exist or is archived.
            DuplicateCompletionError: If user already has completion for this map.
            SlowerThanPendingError: If new time is slower than pending verification.
            CompletionNotFoundError: If referenced completion not found (FK violation).
        """
        map_exists = await self._completions_repo.check_map_exists(data.code)
        if not map_exists:
            raise MapNotFoundError(data.code)

        async with self._pool.acquire() as conn, conn.transaction():
            pending = await self._completions_repo.get_pending_verification(data.user_id, data.code, conn=conn)  # type: ignore
            verification_id_to_delete = None

            if pending:
                if data.time >= pending["time"]:
                    raise SlowerThanPendingError(new_time=data.time, pending_time=pending["time"])

                await self._completions_repo.reject_completion(pending["id"], BOT_USER_ID, conn=conn)  # type: ignore
                verification_id_to_delete = pending["verification_id"]

            try:
                completion_id = await self._completions_repo.insert_completion(
                    code=data.code,
                    user_id=data.user_id,
                    time=data.time,
                    screenshot=data.screenshot,
                    video=data.video,
                    conn=conn,  # type: ignore
                )
            except UniqueConstraintViolationError:
                raise DuplicateCompletionError(user_id=data.user_id, map_code=data.code)
            except ForeignKeyViolationError as e:
                if "user_id" in e.constraint_name:
                    raise CompletionNotFoundError(data.user_id)
                raise MapNotFoundError(data.code)

        if verification_id_to_delete:
            delete_event = VerificationMessageDeleteEvent(verification_id_to_delete)
            await self.publish_message(
                routing_key="api.completion.verification.delete",
                data=delete_event,
                headers=request.headers,
                idempotency_key=None,
            )

        if not completion_id:
            raise ValueError("Completion ID is null after insert")

        suspicious_flags = await self.get_suspicious_flags(data.user_id)

        if not (data.video or suspicious_flags):
            request.app.emit(
                "completion.ocr.requested",
                OcrVerificationRequestedEvent(
                    completion_id=completion_id,
                    user_id=data.user_id,
                    code=data.code,
                    time=data.time,
                    screenshot=data.screenshot,
                ),
                svc=self,
                users=users,
                notifications=notifications,
            )
            return CompletionSubmissionJobResponse(None, completion_id)

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
        unique_error: Exception,
        fk_error: Exception,
    ) -> None:
        """Run a repository write and translate constraint errors to domain exceptions.

        Args:
            operation: The async operation to run.
            unique_error: Domain exception to raise on unique constraint violation.
            fk_error: Domain exception to raise on foreign key violation.

        Raises:
            Domain exceptions as specified by unique_error and fk_error parameters.
        """
        try:
            await operation()
        except UniqueConstraintViolationError:
            raise unique_error
        except ForeignKeyViolationError:
            raise fk_error

    async def edit_completion(self, state: State, record_id: int, data: CompletionPatchRequest) -> None:
        """Apply partial updates to a completion record.

        Raises:
            DuplicateCompletionError: If completion already exists.
            CompletionNotFoundError: If completion or user not found.
        """
        _ = state
        exists = await self._completions_repo.check_completion_exists(record_id)
        if not exists:
            raise CompletionNotFoundError(record_id)

        patch_data = self._build_patch_dict(data)
        try:
            await self._completions_repo.edit_completion(record_id, patch_data)
        except UniqueConstraintViolationError:
            raise DuplicateCompletionError(user_id=0, map_code="unknown")
        except ForeignKeyViolationError:
            raise CompletionNotFoundError(record_id)

    async def check_for_previous_world_record(self, code: OverwatchCode, user_id: int) -> bool:
        """Check if a record submitted by this user has ever received World Record XP."""
        return await self._completions_repo.check_previous_world_record_xp(code, user_id)

    async def get_completion_submission(self, record_id: int) -> CompletionSubmissionResponse:
        """Retrieve detailed submission info for a completion.

        Raises:
            CompletionNotFoundError: If completion not found.
        """
        row = await self._completions_repo.fetch_completion_submission(record_id)
        if not row:
            raise CompletionNotFoundError(record_id)
        return msgspec.convert(row, CompletionSubmissionResponse)

    async def get_pending_verifications(self) -> list[PendingVerificationResponse]:
        """Retrieve completions awaiting verification."""
        rows = await self._completions_repo.fetch_pending_verifications()
        return msgspec.convert(rows, list[PendingVerificationResponse])

    async def verify_completion(
        self,
        request: Request | None,
        record_id: int,
        data: CompletionVerificationUpdateRequest,
        *,
        conn: Connection | None = None,
        notifications: NotificationsService | None = None,
    ) -> JobStatusResponse:
        """Update verification status for a completion and publish an event.

        Args:
            request: HTTP request for headers (optional for event-driven calls).
            record_id: Completion record ID.
            data: Verification update data.
            conn: Database connection (optional).
            notifications: Notifications service for quest completion alerts.

        Returns:
            Job status response.

        Raises:
            DuplicateVerificationError: If verification record already exists.
            CompletionNotFoundError: If completion or user not found.
        """
        exists = await self._completions_repo.check_completion_exists(record_id, conn=conn)
        if not exists:
            raise CompletionNotFoundError(record_id)

        completion_info = await self._completions_repo.fetch_completion_for_moderation(
            record_id,
            conn=conn,  # type: ignore[arg-type]
        )
        if not completion_info:
            raise CompletionNotFoundError(record_id)

        try:
            await self._completions_repo.update_verification(
                record_id,
                data.verified,
                data.verified_by,
                data.reason,
                conn=conn,
            )
        except UniqueConstraintViolationError:
            raise DuplicateVerificationError(record_id)
        except ForeignKeyViolationError:
            raise CompletionNotFoundError(record_id)

        if data.verified and not completion_info["old_verified"]:
            await self._update_quest_progress_for_completion(
                user_id=completion_info["user_id"],
                map_code=completion_info["code"],
                time=completion_info["old_time"],
                notifications=notifications,
                headers=request.headers if request else Headers(),
            )
        if not data.verified and completion_info["old_verified"]:
            await self._revert_quest_progress_for_completion(
                user_id=completion_info["user_id"],
                map_code=completion_info["code"],
                time=completion_info["old_time"],
            )

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
            headers=request.headers if request else Headers(),
            idempotency_key=idempotency_key,
        )
        return job_status

    async def verify_completion_with_pool(
        self,
        request: Request | None,
        record_id: int,
        data: CompletionVerificationUpdateRequest,
        notifications: NotificationsService | None = None,
    ) -> JobStatusResponse:
        """Verify completion using pool connection."""
        async with self._pool.acquire() as conn:
            return await self.verify_completion(
                request,
                record_id,
                data,
                conn=conn,  # type: ignore
                notifications=notifications,
            )

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
        """Insert a suspicious flag for a completion.

        Raises:
            DuplicateFlagError: If flag already exists.
            CompletionNotFoundError: If completion or user not found.
        """
        try:
            await self._completions_repo.insert_suspicious_flag(
                message_id=data.message_id,
                verification_id=data.verification_id,
                context=data.context,
                flag_type=data.flag_type,
                flagged_by=data.flagged_by,
            )
        except UniqueConstraintViolationError:
            raise DuplicateFlagError(data.verification_id or 0)
        except ForeignKeyViolationError:
            raise CompletionNotFoundError(data.verification_id or 0)

    async def get_upvotes_from_message_id(self, message_id: int) -> int:
        """Get the upvotes for a particular completion by message_id."""
        return await self._completions_repo.fetch_upvote_count(message_id)

    async def upvote_submission(self, request: Request, data: UpvoteCreateRequest) -> UpvoteSubmissionJobResponse:
        """Upvote a completion submission.

        Raises:
            DuplicateUpvoteError: If user already upvoted this completion.
            CompletionNotFoundError: If completion or user not found.
        """
        try:
            count = await self._completions_repo.insert_upvote(data.user_id, data.message_id)
        except UniqueConstraintViolationError:
            raise DuplicateUpvoteError(data.user_id, data.message_id)
        except ForeignKeyViolationError:
            raise CompletionNotFoundError(data.message_id)
        upvote_channel_amount_breakpoint = 10
        if count is None:
            raise DuplicateUpvoteError(data.user_id, data.message_id)
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

    async def get_dashboard_completions(
        self, user_id: int, page_size: int, page_number: int
    ) -> list[DashboardCompletionResponse]:
        """Get completions for a user's dashboard with verification status."""
        rows = await self._completions_repo.fetch_dashboard_completions(user_id, page_size, page_number)
        return msgspec.convert(rows, list[DashboardCompletionResponse])

    async def set_quality_vote_for_map_code(self, code: OverwatchCode, user_id: int, quality: int) -> None:
        """Set the quality vote for a map code per user.

        Raises:
            DuplicateQualityVoteError: If quality vote already exists.
            MapNotFoundError: If map not found.
            CompletionNotFoundError: If user not found.
        """
        map_exists = await self._completions_repo.check_map_exists(code)
        if not map_exists:
            raise MapNotFoundError(code)

        try:
            await self._completions_repo.upsert_quality_vote(code, user_id, quality)
        except UniqueConstraintViolationError:
            raise DuplicateQualityVoteError(user_id, 0)
        except ForeignKeyViolationError as e:
            if "map" in e.constraint_name.lower():
                raise MapNotFoundError(code)
            raise CompletionNotFoundError(user_id)

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
        notification_service: NotificationsService | None = None,
        headers: Headers | None = None,
    ) -> None:
        """Moderate a completion record.

        Raises:
            CompletionNotFoundError: If completion not found.
            DuplicateCompletionError: If completion already exists.
        """
        completion_info = await self._completions_repo.fetch_completion_for_moderation(completion_id)
        if not completion_info:
            raise CompletionNotFoundError(completion_id)

        user_id = completion_info["user_id"]
        map_code = completion_info["code"]
        old_time = completion_info["old_time"]
        old_verified = completion_info["old_verified"]

        notification_messages: list[str] = []

        if data.time is not msgspec.UNSET:
            if data.time_change_reason is msgspec.UNSET:
                raise ValueError("time_change_reason is required when changing time")
            new_time = cast(float, data.time)
            await self._run_repo_write(
                lambda: self._completions_repo.update_completion_time(completion_id, new_time),
                unique_error=DuplicateCompletionError(user_id, map_code),
                fk_error=CompletionNotFoundError(completion_id),
            )
            notification_messages.append(
                f"Your completion time on **{map_code}** was changed from **{old_time}s** to **{new_time}s**.\n"
                f"Reason: {data.time_change_reason}"
            )

        if data.verified is not msgspec.UNSET:
            verified = cast(bool, data.verified)
            await self._run_repo_write(
                lambda: self._completions_repo.update_completion_verified(completion_id, verified),
                unique_error=DuplicateCompletionError(user_id, map_code),
                fk_error=CompletionNotFoundError(completion_id),
            )

            if verified != old_verified:
                if verified:
                    await self._update_quest_progress_for_completion(
                        user_id=user_id,
                        map_code=map_code,
                        time=old_time,
                        notifications=notification_service,
                        headers=headers if headers else Headers(),
                    )
                else:
                    await self._revert_quest_progress_for_completion(
                        user_id=user_id,
                        map_code=map_code,
                        time=old_time,
                    )
                if verified:
                    notification_messages.append(f"Your completion on **{map_code}** has been verified by a moderator.")
                else:
                    reason_msg = f"\nReason: {data.verification_reason}" if data.verification_reason else ""
                    notification_messages.append(
                        f"Your completion on **{map_code}** has been unverified by a moderator.{reason_msg}"
                    )

        if data.mark_suspicious:
            if data.suspicious_context is msgspec.UNSET or data.suspicious_flag_type is msgspec.UNSET:
                raise ValueError("suspicious_context and suspicious_flag_type are required when marking as suspicious")
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
                    unique_error=DuplicateFlagError(completion_id),
                    fk_error=CompletionNotFoundError(completion_id),
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
