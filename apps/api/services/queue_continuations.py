"""Durable API continuations with HTTP outside the decision transaction."""

from __future__ import annotations

import datetime as dt
import logging
import os

import aiohttp
import msgspec
from asyncpg import Connection
from genjishimada_sdk.completions import (
    CompletionCreatedEvent,
    CompletionVerificationUpdateRequest,
    ExtractedResultResponse,
    FailedAutoverifyEvent,
    OcrResponse,
)
from genjishimada_sdk.newsfeed import NewsfeedEvent, NewsfeedLinkedMap
from genjishimada_sdk.notifications import NotificationCreateRequest, NotificationEventType
from genjishimada_sdk.queue import JobContext
from genjishimada_sdk.queue_store import lock_claim
from genjishimada_sdk.queue_worker import QueueWorker
from litestar.datastructures import Headers, State

from repository.completions_repository import CompletionsRepository
from repository.lootbox_repository import LootboxRepository
from repository.newsfeed_repository import NewsfeedRepository
from repository.notifications_repository import NotificationsRepository
from repository.tournaments_repository import TournamentRepository
from repository.users_repository import UsersRepository
from services.completions_service import BOT_USER_ID, CompletionsService
from services.lootbox_service import LootboxService
from services.newsfeed_service import NewsfeedService
from services.notifications_service import NotificationsService
from services.tournament_reward_service import TournamentRewardService
from services.users_service import UsersService
from utilities.transactions import transaction

log = logging.getLogger(__name__)


class QueueContinuations:
    """Build fresh services and commit each decision alongside its downstream jobs."""

    def __init__(self, state: State) -> None:
        self.state = state
        pool = state.db_pool
        tournament_repo = TournamentRepository(pool)
        lootbox_repo = LootboxRepository(pool)
        rewards = TournamentRewardService(
            pool, state, tournament_repo, lootbox_repo, LootboxService(pool, state, lootbox_repo)
        )
        self.completions = CompletionsService(pool, state, CompletionsRepository(pool), tournament_repo, rewards)
        self.users = UsersService(pool, state, UsersRepository(pool))
        self.notifications = NotificationsService(pool, state, NotificationsRepository(pool), UsersRepository(pool))
        self.newsfeed = NewsfeedService(pool, state, NewsfeedRepository(pool))

    async def _pending(self, payload: dict, tournament: bool, *, conn: Connection | None = None) -> bool:
        pool = conn or self.state.db_pool
        if tournament:
            return bool(
                await pool.fetchval(
                    "SELECT status='pending' FROM tournaments.completions WHERE id=$1",
                    payload["tournament_completion_id"],
                )
            )
        return bool(
            await pool.fetchval(
                "SELECT NOT verified AND verified_by IS NULL FROM core.completions WHERE id=$1",
                payload["completion_id"],
            )
        )

    async def extract(self, payload: dict, names: list[str]) -> ExtractedResultResponse:
        """Call the OCR boundary with a bounded timeout and no open transaction."""
        hostname = "genjishimada-ocr" if os.getenv("APP_ENVIRONMENT") == "production" else "genjishimada-ocr-dev"
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session,
            session.post(
                f"http://{hostname}:8000/extract",
                json={
                    "image_url": payload["screenshot"],
                    "code": payload["code"],
                    "time": payload["time"],
                    "names": names,
                },
            ) as response,
        ):
            response.raise_for_status()
            return msgspec.json.decode(await response.read(), type=OcrResponse).extracted

    async def ocr(self, context: JobContext) -> None:  # noqa: PLR0912 - one locked OCR decision
        """Fetch OCR once per attempt, then commit one decision despite process death."""
        payload = msgspec.json.decode(context.payload)
        tournament = context.event_name == "tournament.ocr.requested"
        if not await self._pending(payload, tournament):
            return
        if await self.state.db_pool.fetchval(
            "SELECT 1 FROM public.job_effects WHERE job_id=$1 AND effect_key='ocr-decision' AND state='completed'",
            context.job_id,
        ):
            return
        # Database reads must not be classified as OCR service errors.
        names = [name.upper() for name in await self.users.fetch_all_user_names(payload["user_id"])]
        extracted = None
        ocr_error = False
        matched = False
        code_match = time_match = user_match = False
        try:
            extracted = await self.extract(payload, names)
            code_match = payload["code"] == extracted.code
            time_match = payload["time"] == extracted.time
            user_match = extracted.name in names
            matched = code_match and time_match and user_match
        except (aiohttp.ClientError, TimeoutError, msgspec.DecodeError):
            log.exception("OCR service failed for queued job %s", context.job_id)
            ocr_error = True
        # Failures below here propagate to the queue; a failed commit is never a
        # completed OCR job or a second contradictory manual-review decision.
        async with transaction(self.state.db_pool) as conn:
            await lock_claim(conn, context)
            if await conn.fetchval(
                "SELECT 1 FROM public.job_effects WHERE job_id=$1 AND effect_key='ocr-decision'", context.job_id
            ):
                return
            table = "tournaments.completions" if tournament else "core.completions"
            identity = payload["tournament_completion_id"] if tournament else payload["completion_id"]
            current = await conn.fetchrow(
                f"""SELECT c.user_id,c.time,c.screenshot,m.code FROM {table} c
                JOIN core.maps m ON m.id=c.map_id WHERE c.id=$1 FOR UPDATE OF c""",
                identity,
            )
            if not await self._pending(payload, tournament, conn=conn):
                return
            if current is None or any(
                current[field] != payload[field] for field in ("user_id", "time", "screenshot", "code")
            ):
                # The queued proof may have been edited while OCR was in flight.
                # Preserve manual review instead of approving a different result
                # based on the old screenshot. The review handler fetches current data.
                matched = False
                extracted = None
                if current is not None:
                    payload = {**payload, **dict(current)}
            if matched:
                if tournament:
                    await self.completions.verify_tournament_completion(identity)
                else:
                    await self.completions.verify_completion_with_pool(
                        None,
                        identity,
                        CompletionVerificationUpdateRequest(
                            verified_by=BOT_USER_ID,
                            verified=True,
                            reason="Auto Verified by Genji Shimada.",
                        ),
                        notifications=self.notifications,
                    )
            else:
                if tournament:
                    await self.completions._publish_tournament_mod_review(  # noqa: SLF001
                        tournament_completion_id=identity,
                        cycle_id=payload["cycle_id"],
                        user_id=payload["user_id"],
                        time=payload["time"],
                        screenshot=payload["screenshot"],
                        idempotency_key=f"tournament:submission:{payload['user_id']}:{identity}",
                    )
                else:
                    if extracted is not None:
                        await self.completions.enqueue(
                            routing_key="api.completion.autoverification.failed",
                            data=FailedAutoverifyEvent(
                                submitted_code=payload["code"],
                                submitted_time=payload["time"],
                                submitted_user_names=names,
                                user_id=payload["user_id"],
                                extracted=extracted,
                                code_match=code_match,
                                time_match=time_match,
                                user_match=user_match,
                                screenshot=payload["screenshot"],
                            ),
                            idempotency_key=f"completion:ocr-failure:{identity}",
                        )
                    await self.completions.enqueue(
                        routing_key="api.completion.submission",
                        data=CompletionCreatedEvent(identity),
                        idempotency_key=f"completion:submission:{payload['user_id']}:{identity}",
                    )
                subject = "tournament completion" if tournament else "completion"
                outcome = "encountered an error" if ocr_error else "failed"
                id_field = "tournament_completion_id" if tournament else "completion_id"
                await self.notifications.create_and_dispatch(
                    NotificationCreateRequest(
                        user_id=payload["user_id"],
                        event_type=NotificationEventType.AUTO_VERIFY_FAILED.value,
                        title="Auto-Verification Failed",
                        body=(
                            f"Auto-verification {outcome} for your {subject} on {payload['code']}. "
                            "Your submission is now awaiting manual verification."
                        ),
                        metadata={id_field: identity, "map_code": payload["code"]},
                    ),
                    Headers(),
                )
            await conn.execute(
                """INSERT INTO public.job_effects(job_id,effect_key,kind,state,fingerprint,result)
                VALUES ($1,'ocr-decision','mutation','completed',$2,$3::jsonb)""",
                context.job_id,
                context.event_key,
                msgspec.json.encode({"matched": matched, "ocr_error": ocr_error}).decode(),
            )

    async def linked_map(self, context: JobContext) -> None:
        """Resolve the successful dependency then persist one linked-map announcement."""
        payload = msgspec.json.decode(context.payload)
        async with transaction(self.state.db_pool) as conn:
            await lock_claim(conn, context)
            if await conn.fetchval(
                "SELECT 1 FROM public.job_effects WHERE job_id=$1 AND effect_key='linked-newsfeed'", context.job_id
            ):
                return
            linked = await conn.fetchval(
                "SELECT id FROM core.maps WHERE code=$1 AND linked_code=$2 FOR UPDATE",
                payload["official_code"],
                payload["unofficial_code"],
            )
            if linked is None:
                # Unlinked, renamed or replaced while this continuation was waiting.
                await conn.execute(
                    """INSERT INTO public.job_effects(job_id,effect_key,kind,state,fingerprint,result)
                    VALUES ($1,'linked-newsfeed','mutation','completed',$2,'{"skipped":"superseded"}')""",
                    context.job_id,
                    context.event_key,
                )
                return
            event_payload = NewsfeedLinkedMap(
                official_code=payload["official_code"], unofficial_code=payload["unofficial_code"]
            )
            if payload["in_playtest"]:
                event_payload.playtest_id = await conn.fetchval(
                    """SELECT p.thread_id FROM playtests.meta p JOIN core.maps m ON m.id=p.map_id
                    WHERE m.code=$1 ORDER BY p.id DESC LIMIT 1""",
                    payload["official_code"],
                )
            await self.newsfeed.create_and_publish(
                event=NewsfeedEvent(
                    id=None,
                    timestamp=dt.datetime.fromisoformat(payload["timestamp"]),
                    payload=event_payload,
                    event_type="linked_map",
                ),
                headers=Headers(),
            )
            await conn.execute(
                """INSERT INTO public.job_effects(job_id,effect_key,kind,state,fingerprint,result)
                VALUES ($1,'linked-newsfeed','mutation','completed',$2,'{}')""",
                context.job_id,
                context.event_key,
            )


def register_continuations(worker: QueueWorker, state: State) -> None:
    """Register the three API-owned durable entrypoints."""

    async def ocr(context: JobContext) -> None:
        await QueueContinuations(state).ocr(context)

    async def linked_map(context: JobContext) -> None:
        await QueueContinuations(state).linked_map(context)

    worker.add_handler("completion.ocr.requested", ocr)
    worker.add_handler("tournament.ocr.requested", ocr)
    worker.add_handler("map.linked.newsfeed.requested", linked_map)
