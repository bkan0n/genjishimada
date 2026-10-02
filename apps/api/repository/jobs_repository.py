from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, TypeVar, cast

from asyncpg import Connection
from genjishimada_sdk import queue_store
from genjishimada_sdk.internal import ClaimCreateRequest, ClaimResponse, JobStatusResponse, JobStatusUpdateRequest
from genjishimada_sdk.queue import DependencyFailed, DependencyUnavailable, JobContext, LostOwnershipError
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_404_NOT_FOUND

from .base import BaseRepository

T = TypeVar("T")


class InternalJobsRepository(BaseRepository):
    async def get_job(self, job_id: uuid.UUID, *, conn: Connection | None = None) -> JobStatusResponse:
        """Get job status."""
        connection = self._get_connection(conn)
        try:
            # This projection performs one read and supports a pool or an explicitly
            # supplied connection, as the legacy repository contract does.
            return await queue_store.get_job(cast(Connection, connection), job_id)
        except LookupError as exc:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def update_job(
        self, job_id: uuid.UUID, data: JobStatusUpdateRequest, *, conn: Connection | None = None
    ) -> None:
        """Update job status."""
        _conn = self._get_connection(conn)

        now = datetime.now(timezone.utc)
        sets = {
            "processing": ("status='processing', started_at=COALESCE(started_at,$2)", (job_id, now)),
            "succeeded": ("status='succeeded', finished_at=$2, error_code=NULL, error_msg=NULL", (job_id, now)),
            "failed": (
                "status='failed', finished_at=$2, error_code=$3, error_msg=$4",
                (job_id, now, data.error_code, data.error_msg),
            ),
            "timeout": (
                "status='timeout', finished_at=$2, error_code=$3, error_msg=$4",
                (job_id, now, data.error_code, data.error_msg),
            ),
            "queued": ("status='queued'", (job_id,)),
        }
        sql_set, params = sets[data.status]
        row = await _conn.fetchrow("SELECT queue_job_id FROM public.jobs WHERE id=$1", job_id)
        if row is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Job not found.")
        if row["queue_job_id"] is not None:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="Queue-backed status is managed by its worker.")
        await _conn.execute(f"UPDATE public.jobs SET {sql_set} WHERE id=$1 AND queue_job_id IS NULL", *params)

    async def perform(self, operation: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:  # noqa: ANN401
        """Run the common recovery service on a real connection and translate failures."""
        try:
            async with self._pool.acquire() as conn:
                return await operation(conn, *args, **kwargs)
        except LostOwnershipError as exc:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc
        except DependencyFailed as exc:
            raise HTTPException(status_code=HTTPStatus.FAILED_DEPENDENCY, detail=str(exc)) from exc
        except DependencyUnavailable as exc:
            raise HTTPException(status_code=HTTPStatus.LOCKED, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc)) from exc

    @staticmethod
    def execution_context(
        job_id: uuid.UUID,
        headers: Mapping[str, str],
        *,
        administrative: bool = False,
    ) -> JobContext | SimpleNamespace:
        """Read claim identity from authenticated requests; the database verifies it."""
        if administrative:
            return SimpleNamespace(job_id=job_id, manager_id=None, claimed_at=None)
        try:
            if uuid.UUID(headers["X-Job-ID"]) != job_id:
                raise ValueError("Route and execution job identities differ")
            manager_id = uuid.UUID(headers["X-Job-Manager"])
            claimed_at = datetime.fromisoformat(headers["X-Job-Claimed-At"])
            if claimed_at.tzinfo is None:
                raise ValueError("Execution timestamp must have a timezone")
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail="A complete execution claim is required."
            ) from exc
        return JobContext(job_id, "", "", 0, manager_id, claimed_at, b"")

    async def inspect_operation(
        self,
        job_id: uuid.UUID,
        *,
        operator_id: int,
        binding: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Inspect metadata only for allowlisted operators and valid control context."""
        if operator_id not in queue_store.operator_ids():
            raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Operator is not permitted to inspect jobs.")
        async with self._pool.acquire() as conn:
            if binding is not None:
                row = await conn.fetchrow("SELECT * FROM public.job_alerts WHERE job_id=$1", job_id)
                if row is None or any(row[name] != value for name, value in binding.items()):
                    raise HTTPException(
                        status_code=HTTPStatus.FORBIDDEN, detail="Control does not match its saved binding."
                    )
            try:
                return await queue_store.inspect_job(cast(Connection, conn), job_id)
            except LookupError as exc:
                raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc

    async def list_operations(
        self,
        *,
        operator_id: int,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List actionable work without loading complete payloads or effect results."""
        if operator_id not in queue_store.operator_ids():
            raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Operator is not permitted to inspect jobs.")
        if status is not None and status not in {"queued", "processing", "failed", "succeeded", "timeout"}:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Unknown job status.")
        if not 1 <= limit <= 100:  # noqa: PLR2004
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Limit must be between 1 and 100.")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id AS job_id,action AS event_name,status::text,retry_generation,
                error_code,error_msg,handler_failures,attempts,created_at,finished_at
                FROM public.jobs WHERE queue_job_id IS NOT NULL
                AND (($1::text IS NULL AND status <> 'succeeded' AND error_code IS DISTINCT FROM 'discarded')
                     OR status::text=$1)
                ORDER BY created_at DESC,id LIMIT $2""",
                status,
                limit,
            )
            return [dict(row) for row in rows]

    async def queue_stats(self, *, operator_id: int) -> dict[str, Any]:
        """Read queue pressure and held uncertainty without exposing job payloads."""
        if operator_id not in queue_store.operator_ids():
            raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Operator is not permitted to inspect jobs.")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""SELECT
                count(*) FILTER(WHERE status='queued' AND execute_after <= now()) AS ready,
                count(*) FILTER(WHERE status='queued' AND execute_after > now()) AS delayed,
                count(*) FILTER(WHERE status='picked') AS processing,
                count(*) FILTER(WHERE status='failed') AS held,
                EXTRACT(epoch FROM max(now()-created) FILTER(
                    WHERE status='queued' AND execute_after <= now()))::double precision AS oldest_ready_age_seconds,
                (SELECT count(*) FROM public.job_effects e JOIN public.jobs j ON j.id=e.job_id
                 WHERE e.kind='external' AND e.state='started' AND j.status='failed') AS uncertain_effects
                FROM public.pgqueuer""")
            assert row is not None
            return dict(row)

    async def pending_alerts(self, *, after: uuid.UUID | None = None) -> list[dict[str, Any]]:
        """Project failures and return only alerts whose persisted rendering is stale."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("""INSERT INTO public.job_alerts(job_id)
                SELECT id FROM public.jobs WHERE queue_job_id IS NOT NULL AND status='failed'
                ON CONFLICT(job_id) DO NOTHING""")
            jobs = await conn.fetch(
                """SELECT j.id FROM public.jobs j JOIN public.job_alerts a ON a.job_id=j.id
                WHERE ($1::uuid IS NULL OR j.id > $1) AND (
                   a.message_id IS NULL OR a.rendered_generation IS DISTINCT FROM j.retry_generation
                   OR a.rendered_status IS DISTINCT FROM j.status::text
                   OR (j.status='failed' AND a.notified_generation IS DISTINCT FROM j.retry_generation)
                   OR EXISTS(SELECT 1 FROM public.job_effects e WHERE e.job_id=j.id
                             AND e.kind <> 'alert' AND e.updated_at > a.updated_at))
                ORDER BY j.id LIMIT 100""",
                after,
            )
            observed_at = await conn.fetchval("SELECT transaction_timestamp()")
            return [
                {
                    **await queue_store.inspect_job(cast(Connection, conn), row["id"]),
                    "observed_at": observed_at.isoformat(),
                }
                for row in jobs
            ]

    async def bind_alert(  # noqa: PLR0913
        self,
        job_id: uuid.UUID,
        *,
        binding: dict[str, int],
        expected_generation: int,
        rendered_status: str,
        notified_generation: int | None,
        observed_at: datetime,
    ) -> dict[str, Any]:
        """Acknowledge rendering only while its generation and status are still current."""
        async with self._pool.acquire() as conn, conn.transaction():
            now = await conn.fetchval("SELECT transaction_timestamp()")
            if observed_at.tzinfo is None or observed_at > now:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Invalid observation timestamp.")
            row = await conn.fetchrow("SELECT retry_generation,status FROM public.jobs WHERE id=$1 FOR UPDATE", job_id)
            if row is None:
                raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Job not found.")
            if row["retry_generation"] != expected_generation or row["status"] != rendered_status:
                return {"accepted": False, "status": row["status"], "retry_generation": row["retry_generation"]}
            if notified_generation is not None and not 0 <= notified_generation <= expected_generation:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Invalid notification generation.")
            updated = await conn.fetchval(
                """UPDATE public.job_alerts SET guild_id=$2,channel_id=$3,message_id=$4,
                rendered_generation=$5,rendered_status=$6,
                notified_generation=CASE WHEN $7::integer IS NULL THEN notified_generation
                    ELSE GREATEST(COALESCE(notified_generation,-1),$7) END,updated_at=$8
                WHERE job_id=$1 RETURNING job_id""",
                job_id,
                binding["guild_id"],
                binding["channel_id"],
                binding["message_id"],
                expected_generation,
                rendered_status,
                notified_generation,
                observed_at,
            )
            if updated is None:
                raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="No failure alert exists.")
            return {"accepted": True}

    async def claim_idempotency(self, data: ClaimCreateRequest, conn: Connection | None = None) -> ClaimResponse:
        """Claim a idempotency key."""
        _conn = self._get_connection(conn)

        tag = await _conn.execute(
            """
            INSERT INTO public.processed_messages (idempotency_key)
            VALUES ($1)
            ON CONFLICT DO NOTHING;
            """,
            data.key,
        )
        claimed = tag.endswith("INSERT 0 1")
        return ClaimResponse(claimed=claimed)

    async def delete_claimed_idempotency(self, data: ClaimCreateRequest, *, conn: Connection | None = None) -> None:
        """Delete a idempotency key."""
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            DELETE FROM public.processed_messages
            WHERE idempotency_key = $1;
            """,
            data.key,
        )


async def provide_internal_jobs_repository(state: State) -> InternalJobsRepository:
    """Litestar DI provider for InternalJobsRepository.

    Args:
        state (State): Provides the application database pool

    Returns:
        InternalJobsRepository: A new service instance.

    """
    return InternalJobsRepository(pool=state.db_pool)
