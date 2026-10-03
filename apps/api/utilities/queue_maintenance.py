"""Bounded retention for completed queue logs; logical jobs and effects are retained."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import asyncpg

log = logging.getLogger(__name__)
RETENTION = timedelta(days=30)
MAINTENANCE_INTERVAL = 3600.0
BATCH_SIZE = 1000


async def prune_completed_job_logs(
    conn: asyncpg.Connection,
    *,
    cutoff: datetime | None = None,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Retain successful summaries and remove old logs atomically in a bounded batch.

    Inconsistent, live, held, and uncertain jobs are skipped. Successful receipts,
    identities, operational audit, alert bindings, and migration evidence survive.
    """
    if not 1 <= batch_size <= BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {BATCH_SIZE}")
    if cutoff is not None and cutoff.tzinfo is None:
        raise ValueError("cutoff must have a timezone")
    async with conn.transaction():
        before = cutoff or await conn.fetchval("SELECT transaction_timestamp() - $1::interval", RETENTION)
        jobs = await conn.fetch(
            """SELECT j.id,j.queue_job_id,terminal.created AS terminal_at
               FROM public.jobs j
               JOIN LATERAL (
                   SELECT created,status FROM public.pgqueuer_log l
                   WHERE l.job_id=j.queue_job_id ORDER BY created DESC,id DESC LIMIT 1
               ) terminal ON terminal.status='successful' AND terminal.created < $1
               WHERE j.status='succeeded' AND j.finished_at < $1
                 AND NOT EXISTS (SELECT 1 FROM public.pgqueuer q WHERE q.id=j.queue_job_id)
                 AND NOT EXISTS (SELECT 1 FROM public.job_effects e WHERE e.job_id=j.id AND e.state='started')
               ORDER BY j.finished_at,j.id LIMIT $2 FOR UPDATE OF j SKIP LOCKED""",
            before,
            batch_size,
        )
        if not jobs:
            return 0
        # Persist the final projection under the same locks and transaction as pruning.
        # Keep the original completion time and all attempt/effect/audit history.
        await conn.executemany(
            """UPDATE public.jobs SET status='succeeded',finished_at=COALESCE(finished_at,$2),
               error_code=NULL,error_msg=NULL WHERE id=$1""",
            [(job["id"], job["terminal_at"]) for job in jobs],
        )
        removed = await conn.fetchval(
            """WITH removed AS (
                   DELETE FROM public.pgqueuer_log WHERE job_id=ANY($1::bigint[]) AND created < $2
                   RETURNING id
               ) SELECT count(*) FROM removed""",
            [job["queue_job_id"] for job in jobs],
            before,
        )
        return int(removed)


async def queue_log_maintenance(
    pool: asyncpg.Pool,
    stop_event: asyncio.Event,
    *,
    interval: float = MAINTENANCE_INTERVAL,
) -> None:
    """Prune in small transactions hourly, stopping before the API pool closes."""
    if interval <= 0:
        raise ValueError("interval must be positive")
    while not stop_event.is_set():
        try:
            while not stop_event.is_set():
                async with pool.acquire() as conn:
                    removed = await prune_completed_job_logs(cast("asyncpg.Connection", conn))
                if removed == 0:
                    break
                log.info("Pruned %s completed queue log records older than 30 days", removed)
                await asyncio.sleep(0)
        except (OSError, RuntimeError, ValueError):
            log.exception("Queue log retention deferred until the next maintenance interval")
        except Exception:  # Database failures must not terminate independent maintenance.
            log.exception("Queue log retention database operation failed; retrying next interval")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue
