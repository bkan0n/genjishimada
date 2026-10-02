"""Fault harness: real PGQueuer worker with two transactionally recorded effects."""

import asyncio
import signal
import logging

logging.basicConfig(level=logging.INFO)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "libs/sdk/src"))
import asyncpg
from genjishimada_sdk.queue_store import apply_mutation, ensure_ready
from genjishimada_sdk.queue_worker import QueueWorker


async def main():
    dsn, marker, phase = sys.argv[1:]
    marker = Path(marker)
    worker = QueueWorker(
        dsn,
        owner="api",
        heartbeat_seconds=0.4,
        drain_seconds=0.15,
        poll_seconds=0.05,
        timeout_seconds=30,
        retry_delays=(0.03, 0.06),
    )

    async def pause(point):
        if phase == point:
            marker.write_text(point)
            while not marker.with_suffix(".release").exists():
                await asyncio.sleep(0.01)

    async def prepare(ctx):
        if phase == "api_outage" and not marker.with_suffix(".release").exists():
            marker.write_text("unavailable")
            raise ConnectionError("API temporarily offline")
        conn = await asyncpg.connect(dsn)
        try:
            await ensure_ready(conn, ctx)
        finally:
            await conn.close()

    async def handle(ctx):
        if phase == "fail":
            raise ValueError("deterministic ordinary failure")
        await pause("before")
        conn = await asyncpg.connect(dsn)
        try:
            for index in (1, 2):

                async def mutate():
                    await conn.execute(
                        "INSERT INTO business_effects VALUES ($1,1) ON CONFLICT(id) DO UPDATE SET value=business_effects.value+1",
                        f"{ctx.job_id}:{index}",
                    )
                    return {"effect": index}

                await apply_mutation(conn, ctx, f"effect:{index}", f"grant:{index}", mutate)
                if index == 1:
                    if phase == "fail_after_first":
                        raise ValueError("deterministic failure after first completed effect")
                    await pause("midway")
            await pause("after")
        finally:
            await conn.close()

    worker.before_job = prepare
    worker.add_handler("completion.ocr.requested", handle)
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, worker.stop)
    await worker.run()


asyncio.run(main())
