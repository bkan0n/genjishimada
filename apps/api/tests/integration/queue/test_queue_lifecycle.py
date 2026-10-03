"""Actual child process and database failures exercise durable recovery."""

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from genjishimada_sdk.queue_store import enqueue_job, get_job, retry_job, inspect_job

pytestmark = [pytest.mark.queue, pytest.mark.queue_fault, pytest.mark.asyncio]
HARNESS = Path(__file__).with_name("worker_process.py")


async def eventually(check, timeout=12):
    async with asyncio.timeout(timeout):
        while True:
            value = await check()
            if value:
                return value
            await asyncio.sleep(0.025)


async def spawn(dsn, tmp_path, phase):
    marker = tmp_path / f"{uuid4().hex}.marker"
    log = marker.with_suffix(".log")
    if directory := os.getenv("QUEUE_ARTIFACT_DIR"):
        artifact = Path(directory) / log.name
        artifact.parent.mkdir(parents=True, exist_ok=True)
        log.symlink_to(artifact)
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(HARNESS), dsn, str(marker), phase, stdout=output, stderr=output
        )
    return process, marker


async def stop(process):
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            process.kill()
            await process.wait()


async def submit(conn):
    async with conn.transaction():
        return await enqueue_job(
            conn, event_name="completion.ocr.requested", payload={"submission": 1}, event_key=str(uuid4())
        )


async def status(dsn, job_id, expected):
    conn = await asyncpg.connect(dsn)
    try:
        return (await get_job(conn, job_id)).status == expected
    finally:
        await conn.close()


@pytest.mark.parametrize("phase", ["before", "midway", "after"])
async def test_Q05_forced_process_death_resumes_only_incomplete_effects(queue_db, queue_dsn, tmp_path, phase):
    public = await submit(queue_db)
    first, marker = await spawn(queue_dsn, tmp_path, phase)
    second = None
    try:

        async def paused():
            return marker.exists()

        await eventually(paused)
        first.kill()
        await first.wait()
        second, _ = await spawn(queue_dsn, tmp_path, "run")
        await eventually(lambda: status(queue_dsn, public.id, "succeeded"))
        values = await queue_db.fetch("SELECT value FROM business_effects ORDER BY id")
        assert [r["value"] for r in values] == [1, 1]
    finally:
        await stop(first)
        if second:
            await stop(second)


async def test_Q06_graceful_drain_timeout_preserves_job(queue_db, queue_dsn, tmp_path):
    public = await submit(queue_db)
    process, marker = await spawn(queue_dsn, tmp_path, "midway")
    try:

        async def paused():
            return marker.exists()

        await eventually(paused)
        process.terminate()
        await asyncio.wait_for(process.wait(), 4)
        assert process.returncode == 0, marker.with_suffix(".log").read_text()
        assert (await get_job(queue_db, public.id)).status == "queued"
    finally:
        await stop(process)


async def test_Q04_accepted_continuation_survives_absent_then_restarted_worker(queue_db, queue_dsn, tmp_path):
    public = await submit(queue_db)
    assert (await get_job(queue_db, public.id)).status == "queued"
    process, _ = await spawn(queue_dsn, tmp_path, "run")
    try:
        await eventually(lambda: status(queue_dsn, public.id, "succeeded"))
        assert await queue_db.fetchval("SELECT sum(value) FROM business_effects") == 2
    finally:
        await stop(process)


async def test_Q19_manual_retry_after_worker_restart_preserves_identity(queue_db, queue_dsn, tmp_path):
    public = await submit(queue_db)
    first, _ = await spawn(queue_dsn, tmp_path, "fail")
    second = None
    try:
        await eventually(lambda: status(queue_dsn, public.id, "failed"))
        await stop(first)
        old = await queue_db.fetchrow("SELECT queue_job_id,event_key FROM jobs WHERE id=$1", public.id)
        result = await retry_job(
            queue_db, public.id, operator_id=7, operator_ids={7}, expected_generation=0, request_id="after-restart"
        )
        assert result["outcome"] == "queued"
        second, _ = await spawn(queue_dsn, tmp_path, "run")
        await eventually(lambda: status(queue_dsn, public.id, "succeeded"))
        new = await queue_db.fetchrow("SELECT queue_job_id,event_key FROM jobs WHERE id=$1", public.id)
        assert old == new
    finally:
        await stop(first)
        if second:
            await stop(second)


async def test_Q07_database_restart_does_not_exhaust_handler_budget(queue_dsn, queue_db, queue_postgres, tmp_path):
    public = await submit(queue_db)
    process, marker = await spawn(queue_dsn, tmp_path, "midway")
    try:

        async def paused():
            return marker.exists()

        await eventually(paused)
        await asyncio.to_thread(
            subprocess.run, ["docker", "restart", queue_postgres["name"]], check=True, capture_output=True
        )
        marker.with_suffix(".release").write_text("continue")

        async def recovered():
            try:
                return await status(queue_dsn, public.id, "succeeded")
            except (OSError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError):
                return False

        try:
            await eventually(recovered, timeout=20)
        except TimeoutError:
            inspect = await asyncpg.connect(queue_dsn)
            rows = await inspect.fetch(
                "SELECT status,heartbeat,queue_manager_id,updated,handler_failures,failure_message FROM pgqueuer"
            )
            await inspect.close()
            pytest.fail(
                f"Worker returncode={process.returncode}; queue={rows}; logs={marker.with_suffix('.log').read_text()}"
            )
        conn = await asyncpg.connect(queue_dsn)
        try:
            assert await conn.fetchval("SELECT handler_failures FROM jobs WHERE id=$1", public.id) == 0
            assert [r["value"] for r in await conn.fetch("SELECT value FROM business_effects")] == [1, 1]
        finally:
            await conn.close()
    finally:
        await stop(process)


async def test_Q08_suspended_old_worker_cannot_repeat_new_worker_effects(queue_db, queue_dsn, tmp_path):
    public = await submit(queue_db)
    first, marker = await spawn(queue_dsn, tmp_path, "before")
    second = None
    try:

        async def paused():
            return marker.exists()

        await eventually(paused)
        os.kill(first.pid, signal.SIGSTOP)
        second, _ = await spawn(queue_dsn, tmp_path, "run")
        await eventually(lambda: status(queue_dsn, public.id, "succeeded"))
        marker.with_suffix(".release").write_text("continue")
        os.kill(first.pid, signal.SIGCONT)
        await stop(first)
        assert [r["value"] for r in await queue_db.fetch("SELECT value FROM business_effects")] == [1, 1]
        assert (await get_job(queue_db, public.id)).status == "succeeded"
    finally:
        if first.returncode is None:
            os.kill(first.pid, signal.SIGCONT)
        await stop(first)
        if second:
            await stop(second)


async def test_Q13_poison_payload_does_not_block_unrelated_work(queue_db, queue_dsn, tmp_path):
    poison = await submit(queue_db)
    await queue_db.execute(
        "UPDATE pgqueuer SET payload=$2 WHERE id=(SELECT queue_job_id FROM jobs WHERE id=$1)",
        poison.id,
        b"invalid envelope",
    )
    healthy = await submit(queue_db)
    process, _ = await spawn(queue_dsn, tmp_path, "run")
    try:
        await eventually(lambda: status(queue_dsn, poison.id, "failed"))
        await eventually(lambda: status(queue_dsn, healthy.id, "succeeded"))
        assert await queue_db.fetchval("SELECT count(*) FROM business_effects") == 2
        assert await queue_db.fetchval("SELECT handler_failures FROM jobs WHERE id=$1", poison.id) == 0
    finally:
        await stop(process)


async def test_Q07_api_outage_defers_without_exhausting_ordinary_budget(queue_db, queue_dsn, tmp_path):
    public = await submit(queue_db)
    process, marker = await spawn(queue_dsn, tmp_path, "api_outage")
    try:

        async def deferred():
            return await queue_db.fetchval("SELECT attempts>=3 FROM jobs WHERE id=$1", public.id)

        await eventually(deferred)
        assert await queue_db.fetchval("SELECT handler_failures FROM jobs WHERE id=$1", public.id) == 0
        assert await queue_db.fetchval("SELECT count(*) FROM job_alerts") == 0
        marker.with_suffix(".release").write_text("API recovered")
        await eventually(lambda: status(queue_dsn, public.id, "succeeded"))
        assert await queue_db.fetchval("SELECT sum(value) FROM business_effects") == 2
    finally:
        await stop(process)
