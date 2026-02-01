from __future__ import annotations

import uuid
from datetime import datetime, timezone

from asyncpg import Connection
from genjishimada_sdk.internal import ClaimCreateRequest, ClaimResponse, JobStatusResponse, JobStatusUpdateRequest
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_404_NOT_FOUND

from .base import BaseRepository


class InternalJobsRepository(BaseRepository):
    async def get_job(self, job_id: uuid.UUID, *, conn: Connection | None = None) -> JobStatusResponse:
        """Get job status."""
        _conn = self._get_connection(conn)

        row = await _conn.fetchrow(
            "SELECT id, status::text, error_code, error_msg FROM public.jobs WHERE id=$1",
            job_id,
        )
        if not row:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Job not found.")
        return JobStatusResponse(
            id=row["id"], status=row["status"], error_code=row["error_code"], error_msg=row["error_msg"]
        )

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
        await _conn.execute(f"UPDATE public.jobs SET {sql_set} WHERE id=$1", *params)

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
        state (State): Used for RabbitMQ and db_pool

    Returns:
        InternalJobsRepository: A new service instance.

    """
    return InternalJobsRepository(pool=state.db_pool)
