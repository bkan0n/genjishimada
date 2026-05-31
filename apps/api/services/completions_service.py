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
from asyncpg.exceptions import CheckViolationError
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
from genjishimada_sdk.tournaments import (
    TournamentCompletionCreatedEvent,
    TournamentVerificationChangedEvent,
)
from litestar import Request
from litestar.datastructures import Headers, State

from events.schemas import OcrVerificationRequestedEvent, TournamentOcrVerificationRequestedEvent
from repository.completions_repository import CompletionsRepository
from repository.exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)
from repository.lootbox_repository import LootboxRepository
from repository.store_repository import StoreRepository
from repository.tournaments_repository import TournamentRepository
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
from .lootbox_service import LootboxService
from .store_service import StoreService
from .tournament_reward_service import TournamentRewardService, provide_tournament_reward_service
from .tournament_service import TournamentService
from .users_service import UsersService

if TYPE_CHECKING:
    from .notifications_service import NotificationsService

log = getLogger(__name__)

BOT_USER_ID = 969632729643753482


class CompletionsService(BaseService):
    """Service for completions domain."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        completions_repo: CompletionsRepository,
        tournament_repo: TournamentRepository | None = None,
        tournament_reward_service: TournamentRewardService | None = None,
    ) -> None:
        """Initialize completions service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            completions_repo: Completions repository.
            tournament_repo: Tournament repository for auto-detecting the active
                cycle by map_id (D-01) and linking the PB cross-write (D-04).
                Optional so existing 3-arg unit tests keep working; the DI
                provider always supplies one in production.
            tournament_reward_service: Reward service used inside verify_completion
                to award participation XP when a linked tournament row is verified
                (D-04a). Optional for the same reason as above.
        """
        super().__init__(pool, state)
        self._completions_repo = completions_repo
        self._tournament_repo = tournament_repo
        self._tournament_reward_service = tournament_reward_service

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
        lootbox_service = LootboxService(self._pool, self._state, lootbox_repo)
        store_service = StoreService(self._pool, self._state, store_repo, lootbox_repo, lootbox_service)
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
            users_repo = UsersRepository(self._pool)

            for quest in completed_quests:
                requirements = quest.get("requirements", {})
                bounty_type = quest.get("bounty_type")
                rival_user_id = requirements.get("rival_user_id")
                rival_display_name = None

                # Always fetch completer display name (needed for 3rd-person body text)
                completer_user = await users_repo.fetch_user(user_id)
                completer_display_name = completer_user["coalesced_name"] if completer_user else "Unknown User"

                if rival_user_id:
                    rival_user = await users_repo.fetch_user(rival_user_id)
                    rival_display_name = rival_user["coalesced_name"] if rival_user else "Unknown User"

                # Build body per quest type
                coins = quest.get("coin_reward", 0)
                xp = quest.get("xp_reward", 0)
                reward_suffix = f" and earned {coins} coins + {xp} XP."

                # Build enriched metadata (base fields)
                metadata: dict[str, Any] = {
                    "quest_id": quest.get("quest_id"),
                    "progress_id": quest.get("progress_id"),
                    "quest_name": quest["name"],
                    "quest_difficulty": quest.get("difficulty"),
                    "coin_reward": quest.get("coin_reward"),
                    "xp_reward": quest.get("xp_reward"),
                    "completer_display_name": completer_display_name,
                    "rival_user_id": rival_user_id,
                    "rival_display_name": rival_display_name,
                }

                # Build body and type-specific metadata per quest type
                if bounty_type == "rival_challenge":
                    rival_time = requirements.get("rival_time")
                    body = (
                        f"{completer_display_name} beat {rival_display_name}'s time on {map_code} "
                        f"({rival_time:.2f}s \u2192 {time:.2f}s){reward_suffix}"
                    )
                    metadata.update(
                        bounty_type=bounty_type, map_code=map_code, completion_time=float(time), rival_time=rival_time
                    )
                elif bounty_type == "personal_improvement":
                    target_time = requirements.get("target_time")
                    body = (
                        f"{completer_display_name} improved their time on {map_code} "
                        f"({target_time:.2f}s \u2192 {time:.2f}s){reward_suffix}"
                    )
                    metadata.update(
                        bounty_type=bounty_type, map_code=map_code, completion_time=float(time), target_time=target_time
                    )
                elif bounty_type == "gap_filling":
                    body = f"{completer_display_name} completed {map_code}{reward_suffix}"
                    metadata.update(bounty_type=bounty_type, map_code=map_code)
                else:
                    description = quest.get("description", "")
                    desc_part = f" ({description})" if description else ""
                    body = f"{completer_display_name} completed '{quest['name']}'{desc_part}{reward_suffix}"
                    metadata["quest_description"] = description

                await notifications.create_and_dispatch(
                    data=NotificationCreateRequest(
                        user_id=user_id,
                        event_type=NotificationEventType.QUEST_COMPLETE,  # type: ignore
                        title="Quest Completed!",
                        body=body,
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
        lootbox_service = LootboxService(self._pool, self._state, lootbox_repo)
        store_service = StoreService(self._pool, self._state, store_repo, lootbox_repo, lootbox_service)
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

    async def attempt_tournament_auto_verify_async(  # noqa: PLR0913
        self,
        tournament_completion_id: int,
        cycle_id: int,
        user_id: int,
        code: str,
        time: float,
        screenshot: str,
        *,
        users: UsersService,
        notifications: NotificationsService | None = None,
    ) -> None:
        """Attempt to OCR-auto-verify a non-PB tournament completion (D-04).

        Mirrors :meth:`attempt_auto_verify_async` 1:1 — same hostname switch,
        ``/extract`` POST, and three-way code/time/name match — but the terminal
        differs (P4): there is NO core completion row for a non-PB run, so on a
        match this verifies the TOURNAMENT row via
        :meth:`TournamentService.verify_tournament_completion` (NOT
        ``verify_completion_with_pool``), and on a mismatch it escalates to bot mod
        review by publishing a TournamentCompletionCreatedEvent (NOT
        ``CompletionCreatedEvent``). Any failure falls back to mod review.

        Args:
            tournament_completion_id: Tournament completion row ID.
            cycle_id: Active cycle ID (carried to the mod-review event).
            user_id: User who submitted the completion.
            code: Map code.
            time: Completion time.
            screenshot: Screenshot URL.
            users: Users service for fetching user names.
            notifications: Notifications service for failure notifications.
        """
        _ = cycle_id  # reserved for the mod-review embed enrichment (11-05)
        idempotency_key = f"tournament:submission:{user_id}:{tournament_completion_id}"

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
                await self.verify_tournament_completion(tournament_completion_id)
                return

            await self._publish_tournament_mod_review(
                tournament_completion_id=tournament_completion_id,
                cycle_id=cycle_id,
                user_id=user_id,
                time=time,
                screenshot=screenshot,
                idempotency_key=idempotency_key,
            )

            if notifications:
                await notifications.create_and_dispatch(
                    data=NotificationCreateRequest(
                        user_id=user_id,
                        event_type=NotificationEventType.AUTO_VERIFY_FAILED,  # type: ignore
                        title="Auto-Verification Failed",
                        body=(
                            f"Auto-verification failed for your tournament completion on {code}. "
                            "Your submission is now awaiting manual verification."
                        ),
                        metadata={"tournament_completion_id": tournament_completion_id, "map_code": code},
                    ),
                    headers=Headers(),
                )

        except Exception as e:
            log.exception(
                "Tournament OCR auto-verification failed for tournament_completion_id=%s: %s",
                tournament_completion_id,
                e,
            )
            sentry_sdk.capture_exception(e)

            await self._publish_tournament_mod_review(
                tournament_completion_id=tournament_completion_id,
                cycle_id=cycle_id,
                user_id=user_id,
                time=time,
                screenshot=screenshot,
                idempotency_key=idempotency_key,
            )

            if notifications:
                await notifications.create_and_dispatch(
                    data=NotificationCreateRequest(
                        user_id=user_id,
                        event_type=NotificationEventType.AUTO_VERIFY_FAILED,  # type: ignore
                        title="Auto-Verification Failed",
                        body=(
                            f"Auto-verification encountered an error for your tournament completion on {code}. "
                            "Your submission is now awaiting manual verification."
                        ),
                        metadata={"tournament_completion_id": tournament_completion_id, "map_code": code},
                    ),
                    headers=Headers(),
                )

    async def _publish_tournament_mod_review(  # noqa: PLR0913
        self,
        *,
        tournament_completion_id: int,
        cycle_id: int,
        user_id: int,
        time: float,
        screenshot: str,
        idempotency_key: str,
    ) -> None:
        """Publish a TournamentCompletionCreatedEvent for bot mod review (11-05 consumes).

        Args:
            tournament_completion_id: Tournament completion row ID (carried as completion_id).
            cycle_id: Active cycle ID.
            user_id: Submitting user.
            time: Completion time.
            screenshot: Screenshot URL.
            idempotency_key: Publish idempotency key.
        """
        await self.publish_message(
            routing_key="api.tournament.completion.created",
            data=TournamentCompletionCreatedEvent(
                completion_id=tournament_completion_id,
                cycle_id=cycle_id,
                user_id=user_id,
                time=time,
                video=None,
                screenshot=screenshot,
            ),
            headers=Headers(),
            idempotency_key=idempotency_key,
        )

    async def verify_tournament_completion(self, tournament_completion_id: int) -> None:
        """Verify a tournament completion row via the tournament service (D-04).

        Thin seam used by the OCR auto-verify terminal so the non-PB OCR path and
        the bot mod-review callback share one verify implementation. Builds a
        TournamentService on the pool and delegates; participation XP + the
        verification-changed publish live in the service.

        Args:
            tournament_completion_id: Tournament completion row ID to verify.
        """
        reward_service = (
            self._tournament_reward_service
            if self._tournament_reward_service is not None
            else await provide_tournament_reward_service(
                self._state,
                self._tournament_repo,  # type: ignore[arg-type]
                LootboxRepository(self._pool),
            )
        )
        tournament_service = TournamentService(
            self._pool,
            self._state,
            self._tournament_repo,  # type: ignore[arg-type]
            reward_service=reward_service,
        )
        await tournament_service.verify_tournament_completion(tournament_completion_id)

    async def submit_completion(  # noqa: PLR0912
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

        completion_id: int | None = None
        non_pb_tournament: tuple[int, dict] | None = None
        async with self._pool.acquire() as raw_conn, raw_conn.transaction():
            conn = cast("Connection", raw_conn)
            # D-01 auto-detect: resolve map_id then look up the active cycle so
            # the rest of the submit path can branch on tournament membership
            # inside this transaction.
            active_cycle = await self._resolve_active_cycle(data.code, conn=conn)

            pending = await self._completions_repo.get_pending_verification(data.user_id, data.code, conn=conn)  # type: ignore
            verification_id_to_delete = None

            if pending:
                # D-07: on a tournament map a valid slower-than-PB run must fall
                # through to the speed-trigger relax, so do NOT pre-empt it with
                # the pending-faster precheck. Non-tournament maps keep the
                # existing HTTP-400 behavior unchanged.
                if data.time >= pending["time"] and active_cycle is None:
                    raise SlowerThanPendingError(new_time=data.time, pending_time=pending["time"])

                if data.time < pending["time"]:
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
            except CheckViolationError:
                # The 0017 speed trigger (ERRCODE 23514) rejected a slower-than-PB
                # run. D-07: ONLY relax on a tournament map — record a tournament
                # row with NO core row and NO FK link. On a non-tournament map,
                # re-raise so the existing HTTP-400 path is preserved. Unique/FK
                # violations are NOT caught here, so they still propagate (P7).
                if active_cycle is None:
                    raise
                non_pb_id = await self._record_tournament_completion(active_cycle, data, conn=conn)
                if non_pb_id is not None:
                    # Defer the OCR/mod dispatch until AFTER this transaction
                    # commits (11-03 D-04): no-video -> tournament OCR auto-verify;
                    # video -> publish to the bot mod-review queue.
                    non_pb_tournament = (non_pb_id, active_cycle)
            except UniqueConstraintViolationError:
                raise DuplicateCompletionError(user_id=data.user_id, map_code=data.code)
            except ForeignKeyViolationError as e:
                if "user_id" in e.constraint_name:
                    raise CompletionNotFoundError(data.user_id)
                raise MapNotFoundError(data.code)

            # D-04 PB path: a PB completion on the active cycle map links a
            # tournament row via core.completions.tournament_completion_id in the
            # SAME transaction.
            if active_cycle is not None and completion_id:
                tournament_completion_id = await self._record_tournament_completion(
                    active_cycle, data, conn=conn
                )
                if tournament_completion_id is not None:
                    await self._completions_repo.set_completion_tournament_link(
                        completion_id, tournament_completion_id, conn=conn
                    )

        if verification_id_to_delete:
            delete_event = VerificationMessageDeleteEvent(verification_id_to_delete)
            await self.publish_message(
                routing_key="api.completion.verification.delete",
                data=delete_event,
                headers=request.headers,
                idempotency_key=None,
            )

        # D-07 non-PB dispatch (11-03): the slower-than-PB run has NO core row, so
        # it gets its OWN tournament verification. No-video -> tournament OCR
        # auto-verify (tournament.ocr.requested); video -> bot mod review
        # (api.tournament.completion.created). Either way this completion does not
        # flow through the core completion event path.
        if non_pb_tournament is not None:
            tc_id, cycle = non_pb_tournament
            return await self._dispatch_non_pb_tournament(
                tc_id=tc_id,
                cycle=cycle,
                data=data,
                request=request,
                users=users,
                notifications=notifications,
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

    async def _resolve_active_cycle(self, code: str, *, conn: Connection | None) -> dict | None:
        """Resolve a map code to the active tournament cycle, if any (D-01).

        Returns None when tournament wiring is absent (unit tests), the map code
        has no metadata, or the map is not the active cycle's map.

        Args:
            code: Map code being submitted/verified.
            conn: Active connection (transaction-scoped for submit).

        Returns:
            The active cycle dict (id, category_id, map_id, status) or None.
        """
        if self._tournament_repo is None:
            return None
        map_meta = await self._completions_repo.fetch_map_metadata_by_code(code, conn=conn)
        if not map_meta or map_meta.get("map_id") is None:
            return None
        return await self._tournament_repo.get_active_cycle_by_map_id(map_meta["map_id"], conn=conn)

    async def _record_tournament_completion(
        self,
        active_cycle: dict,
        data: CompletionCreateRequest,
        *,
        conn: Connection,
    ) -> int | None:
        """Insert a tournament completion row for an active-cycle submission.

        Used by BOTH the PB path (caller then sets the core->tournament link) and
        the D-07 non-PB path (no core row, no link).

        Args:
            active_cycle: Active cycle dict (must contain ``id`` and ``map_id``).
            data: The completion submission request.
            conn: Active transaction connection.

        Returns:
            The new tournament completion id, or None if wiring is absent.
        """
        if self._tournament_repo is None:
            return None
        # CR-01: this runs on the submit hot path (both the PB and D-07 non-PB
        # call sites). The 0020 unique constraint on
        # tournaments.completions (cycle_id, user_id, inserted_at) and the cycle/
        # map FKs can fire here; translate them to the same domain exceptions
        # insert_completion uses so a duplicate surfaces as 409 (not a raw 500),
        # mirroring the core-completion path.
        try:
            row = await self._tournament_repo.create_tournament_completion(
                cycle_id=active_cycle["id"],
                user_id=data.user_id,
                map_id=active_cycle["map_id"],
                time=data.time,
                screenshot=data.screenshot,
                video=data.video,
                conn=conn,
            )
        except UniqueConstraintViolationError as e:
            raise DuplicateCompletionError(user_id=data.user_id, map_code=data.code) from e
        except ForeignKeyViolationError as e:
            if "user_id" in e.constraint_name:
                raise CompletionNotFoundError(data.user_id) from e
            raise MapNotFoundError(data.code) from e
        return row.get("id") if row else None

    async def _dispatch_non_pb_tournament(  # noqa: PLR0913
        self,
        *,
        tc_id: int,
        cycle: dict,
        data: CompletionCreateRequest,
        request: Request,
        users: UsersService,
        notifications: NotificationsService,
    ) -> CompletionSubmissionJobResponse:
        """Route a committed non-PB tournament row to OCR or mod review (D-04).

        A slower-than-PB run has no core completion, so it gets its OWN tournament
        verification. No-video runs emit ``tournament.ocr.requested`` for OCR
        auto-verify against the tournament row; video runs publish a
        TournamentCompletionCreatedEvent on ``api.tournament.completion.created``
        for bot mod review (the bot view lands in 11-05). Returns a job response
        with ``completion_id=0`` (there is no core completion id).

        Args:
            tc_id: The new tournament completion row id.
            cycle: The active cycle dict (id, category_id, map_id, status).
            data: The completion submission request.
            request: HTTP request (for the app emit + publish headers).
            users: Users service (passed to the OCR listener).
            notifications: Notifications service (passed to the OCR listener).

        Returns:
            Job response (no core completion, so completion_id is 0).
        """
        if not data.video:
            request.app.emit(
                "tournament.ocr.requested",
                TournamentOcrVerificationRequestedEvent(
                    tournament_completion_id=tc_id,
                    cycle_id=cycle["id"],
                    user_id=data.user_id,
                    code=data.code,
                    time=data.time,
                    screenshot=data.screenshot,
                ),
                svc=self,
                users=users,
                notifications=notifications,
            )
            return CompletionSubmissionJobResponse(job_status=None, completion_id=0)

        job_status = await self.publish_message(
            routing_key="api.tournament.completion.created",
            data=TournamentCompletionCreatedEvent(
                completion_id=tc_id,
                cycle_id=cycle["id"],
                user_id=data.user_id,
                time=data.time,
                video=data.video,
                screenshot=data.screenshot,
            ),
            headers=request.headers,
            idempotency_key=f"tournament:submission:{data.user_id}:{tc_id}",
        )
        return CompletionSubmissionJobResponse(job_status=job_status, completion_id=0)

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

        # D-04a: when a verified core row links a tournament row on an active
        # cycle, propagate the verification to the tournament row + award
        # participation XP, all inside verify_completion (NOT via a bot consumer,
        # since VerificationChangedEvent carries no map_id — P8).
        if data.verified:
            await self._propagate_tournament_verification(
                completion_info=completion_info,
                headers=request.headers if request else Headers(),
                conn=conn,
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

    async def _propagate_tournament_verification(
        self,
        *,
        completion_info: dict,
        headers: Headers,
        conn: Connection | None,
    ) -> None:
        """Flip the linked tournament row verified + award participation (D-04a).

        Runs only when the verified core row links a tournament row whose map is
        an active cycle. ``set_tournament_verified`` and ``award_participation``
        are atomic on a single connection: when ``conn`` is None (the common
        pooled route call), a fresh connection + transaction is acquired (mirrors
        ``verify_completion_with_pool``). XP is idempotent (the 08-01 ledger), so
        this is replay-safe — verifying twice grants once. Deferred XP events are
        flushed AFTER the transaction commits, then the tournament verification
        event is published.

        Args:
            completion_info: Moderation row (user_id, code, tournament_completion_id).
            headers: Request headers for the publish call.
            conn: Active connection (may be None for pooled route calls).
        """
        if self._tournament_repo is None:
            return
        tournament_completion_id = completion_info.get("tournament_completion_id")
        if tournament_completion_id is None:
            return

        async def _do(active_conn: Connection) -> tuple[dict | None, list[Any], dict | None]:
            cycle = await self._resolve_active_cycle(completion_info["code"], conn=active_conn)
            if cycle is None:
                return None, [], None
            row = await self._tournament_repo.set_tournament_verified(  # type: ignore[union-attr]
                tournament_completion_id, conn=active_conn
            )
            events: list[Any] = []
            if self._tournament_reward_service is not None:
                events = await self._tournament_reward_service.award_participation(
                    cycle, completion_info["user_id"], conn=active_conn
                )
            return cycle, events, row

        if conn is None:
            async with self._pool.acquire() as fresh_conn, fresh_conn.transaction():
                active_cycle, pending_events, verified_row = await _do(cast("Connection", fresh_conn))
        else:
            active_cycle, pending_events, verified_row = await _do(conn)

        if active_cycle is None or verified_row is None:
            return

        if self._tournament_reward_service is not None and pending_events:
            await self._tournament_reward_service.publish_xp_events(pending_events)

        event = TournamentVerificationChangedEvent(
            tournament_completion_id=tournament_completion_id,
            cycle_id=active_cycle["id"],
            user_id=completion_info["user_id"],
            verified=True,
            time=float(verified_row["time"]),
        )
        await self.publish_message(
            routing_key="api.tournament.verification.changed",
            data=event,
            headers=headers,
            idempotency_key=f"tournament:verify:{tournament_completion_id}",
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
    tournament_repo: TournamentRepository,
    tournament_reward_service: TournamentRewardService,
) -> CompletionsService:
    """Litestar DI provider for CompletionsService.

    Args:
        state: Application state containing the database pool.
        completions_repo: Completions repository.
        tournament_repo: Tournament repository for auto-detect + cross-write link.
        tournament_reward_service: Reward service for participation XP on verify.

    Returns:
        CompletionsService wired with tournament dependencies.
    """
    return CompletionsService(
        state.db_pool,
        state,
        completions_repo,
        tournament_repo=tournament_repo,
        tournament_reward_service=tournament_reward_service,
    )
