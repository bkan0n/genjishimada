"""HTTP acceptance for actual recovery routes, authorization, and committed state."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from genjishimada_sdk import queue_store
from litestar import Litestar, Router
from litestar.datastructures import State
from litestar.middleware import DefineMiddleware
from httpx import ASGITransport, AsyncClient

from middleware.auth import CustomAuthenticationMiddleware
from middleware.guards import scope_guard
from routes.v3.jobs import InternalJobsController

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]
OPERATOR = 141372217677053952
BASE = "/api/v3/internal/jobs"


@pytest.fixture
def response_fault():
    return {"drop_retry_response": False}


@pytest.fixture
async def queue_http(queue_dsn, queue_db, monkeypatch, response_fault):
    monkeypatch.setenv("QUEUE_OPERATOR_IDS", str(OPERATOR))
    await queue_db.execute("""
        CREATE TABLE auth_users(id bigint PRIMARY KEY, username text, info text);
        CREATE TABLE api_tokens(api_key text PRIMARY KEY, user_id bigint REFERENCES auth_users(id),
            is_superuser boolean DEFAULT false, scopes text[] NOT NULL DEFAULT '{}');
        INSERT INTO auth_users VALUES(1,'queue-acceptance',NULL);
        INSERT INTO api_tokens(api_key,user_id,scopes) VALUES('manage',1,'{jobs:manage}'),('denied',1,'{}');
        INSERT INTO api_tokens(api_key,user_id,is_superuser) VALUES('superuser',1,true);
    """)
    pool = await asyncpg.create_pool(queue_dsn, min_size=1, max_size=4)
    app = Litestar(
        route_handlers=[Router(path="/api/v3", route_handlers=[InternalJobsController])],
        state=State({"db_pool": pool}),
        middleware=[DefineMiddleware(CustomAuthenticationMiddleware)],
        guards=[scope_guard],
    )

    async def fault_transport(scope, receive, send):
        if response_fault["drop_retry_response"] and scope["method"] == "POST" and scope["path"].endswith("/retry"):
            response_fault["drop_retry_response"] = False
            messages = []

            async def buffer_response(message):
                messages.append(message)

            # Let the real controller commit, but drop the server response before
            # the HTTP client receives any headers or body.
            await app(scope, receive, buffer_response)
            response_fault["dropped_status"] = messages[0]["status"]
            raise ConnectionResetError("Connection closed after retry transaction committed")
        await app(scope, receive, send)

    try:
        async with AsyncClient(transport=ASGITransport(app=fault_transport), base_url="http://queue.test") as client:
            client.headers["X-API-KEY"] = "manage"
            yield client
    finally:
        await pool.close()


async def held_job(conn):
    async with conn.transaction():
        public = await queue_store.enqueue_job(
            conn,
            event_name="api.newsfeed.create",
            event_key=str(uuid4()),
            payload={"newsfeed_id": 1},
        )
    await conn.execute(
        """UPDATE pgqueuer SET status='failed',handler_failures=6,
        failure_code='handler_failed',failure_message='A fixed application fault' WHERE dedupe_key=$1""",
        str(public.id),
    )
    return public.id


def retry_request(**overrides):
    return {"operator_id": OPERATOR, "expected_generation": 0, "request_id": str(uuid4()), **overrides}


async def test_Q20_http_concurrent_retries_commit_one_generation(queue_http, queue_db):
    job_id = await held_job(queue_db)
    responses = await asyncio.gather(
        *(queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request()) for _ in range(2))
    )
    assert [r.status_code for r in responses] == [200, 200]
    assert sorted(r.json()["outcome"] for r in responses) == ["already_queued", "queued"]
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 1
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", job_id) == 1


async def test_Q19_Q23_lost_response_retry_returns_same_durable_result(queue_http, queue_db, response_fault):
    job_id = await held_job(queue_db)
    payload = retry_request()
    response_fault["drop_retry_response"] = True
    with pytest.raises(ConnectionResetError):
        await queue_http.post(f"{BASE}/{job_id}/retry", json=payload)
    assert response_fault["dropped_status"] == 200
    committed = json.loads(await queue_db.fetchval("SELECT result FROM job_operations WHERE job_id=$1", job_id))
    repeated = await queue_http.post(f"{BASE}/{job_id}/retry", json=payload)
    assert repeated.status_code == 200
    assert repeated.json() == committed
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 1
    inspected = await queue_http.get(f"{BASE}/{job_id}/operations", params={"operator_id": OPERATOR})
    assert inspected.status_code == 200
    assert inspected.json()["status"] == "queued"
    assert inspected.json()["handler_failures"] == 0


@pytest.mark.parametrize(
    "credential,actor,expected",
    [
        ("invalid", OPERATOR, 401),
        ("denied", OPERATOR, 401),
        ("manage", OPERATOR + 1, 403),
    ],
)
async def test_Q21_http_authentication_scope_and_actor_reject_before_mutation(
    queue_http,
    queue_db,
    credential,
    actor,
    expected,
):
    job_id = await held_job(queue_db)
    response = await queue_http.post(
        f"{BASE}/{job_id}/retry",
        headers={"X-API-KEY": credential},
        json=retry_request(operator_id=actor),
    )
    assert response.status_code == expected
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", job_id) == 0
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 0


async def test_Q21_bound_operation_rejects_forged_or_partial_context(queue_http, queue_db):
    job_id = await held_job(queue_db)
    await queue_db.execute("UPDATE job_alerts SET guild_id=1,channel_id=2,message_id=3 WHERE job_id=$1", job_id)
    forged = await queue_http.post(
        f"{BASE}/{job_id}/retry",
        json=retry_request(guild_id=1, channel_id=2, message_id=999),
    )
    partial = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request(guild_id=1))
    assert forged.status_code == 403
    assert partial.status_code == 400
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", job_id) == 0


async def test_Q24_old_generation_cannot_retry_new_failure(queue_http, queue_db):
    job_id = await held_job(queue_db)
    accepted = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
    assert accepted.json()["retry_generation"] == 1
    await queue_db.execute("UPDATE pgqueuer SET status='failed' WHERE dedupe_key=$1", str(job_id))
    stale = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
    assert stale.status_code == 200
    assert stale.json()["outcome"] == "stale"
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 1


async def test_Q22_unresolved_effect_is_visible_and_blocks_http_retry(queue_http, queue_db):
    job_id = await held_job(queue_db)
    await queue_db.execute(
        """INSERT INTO job_effects(job_id,effect_key,kind,state,fingerprint,destination)
        VALUES($1,'external-step','external','started','fingerprint','destination')""",
        job_id,
    )
    response = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
    assert response.status_code == 200
    assert response.json()["outcome"] == "requires_reconciliation"
    inspect = await queue_http.get(f"{BASE}/{job_id}/operations", params={"operator_id": OPERATOR})
    assert inspect.json()["effects"][0]["state"] == "started"
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", job_id) == 0


async def test_Q16_legacy_status_patch_cannot_override_queue_state(queue_http, queue_db):
    job_id = await held_job(queue_db)
    response = await queue_http.patch(
        f"{BASE}/{job_id}",
        headers={"X-API-KEY": "superuser"},
        json={"status": "succeeded"},
    )
    assert response.status_code == 409
    status = await queue_http.get(f"{BASE}/{job_id}", headers={"X-API-KEY": "superuser"})
    assert status.status_code == 200
    assert status.json()["status"] == "failed"


async def test_Q18_failure_state_is_available_without_a_worker_status_patch(queue_http, queue_db):
    job_id = await held_job(queue_db)
    response = await queue_http.get(f"{BASE}/{job_id}/operations", params={"operator_id": OPERATOR})
    assert response.status_code == 200
    value = response.json()
    assert value["status"] == "failed"
    assert value["handler_failures"] == 6
    assert value["error_msg"] == "A fixed application fault"


async def test_Q21_execution_endpoints_require_active_claim(queue_http, queue_db):
    job_id = await held_job(queue_db)
    missing = await queue_http.post(f"{BASE}/{job_id}/prepare")
    forged = await queue_http.post(
        f"{BASE}/{job_id}/prepare",
        headers={
            "X-Job-ID": str(job_id),
            "X-Job-Manager": str(uuid4()),
            "X-Job-Claimed-At": "2026-01-01T00:00:00+00:00",
        },
    )
    assert missing.status_code == 400
    assert forged.status_code == 409


async def test_Q17_operator_list_reports_persisted_failure_budget(queue_http, queue_db):
    job_id = await held_job(queue_db)
    response = await queue_http.get(BASE, params={"operator_id": OPERATOR, "status": "failed"})
    assert response.status_code == 200
    assert response.json()[0]["job_id"] == str(job_id)
    assert response.json()[0]["handler_failures"] == 6
    denied = await queue_http.get(BASE, params={"operator_id": OPERATOR + 1})
    assert denied.status_code == 403


async def test_Q22_effect_reconciliation_is_audited_and_releases_retry(queue_http, queue_db):
    job_id = await held_job(queue_db)
    await queue_db.execute(
        """INSERT INTO job_effects(job_id,effect_key,kind,state,fingerprint,destination)
        VALUES($1,'external-step','external','started','fingerprint','destination')""",
        job_id,
    )
    response = await queue_http.post(
        f"{BASE}/{job_id}/effects/external-step/reconcile",
        json={
            "expected_generation": 0,
            "operator_id": OPERATOR,
            "request_id": str(uuid4()),
            "reason": "Located external operation receipt",
            "result": {"external_id": 123},
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "completed"
    retry = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
    assert retry.status_code == 200
    assert retry.json()["outcome"] == "queued"
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 2
    assert await queue_db.fetchval("SELECT state FROM job_effects WHERE job_id=$1", job_id) == "completed"


async def active_claim(conn, job_id):
    manager_id = uuid4()
    row = await conn.fetchrow(
        """UPDATE pgqueuer SET status='picked',queue_manager_id=$2,updated=clock_timestamp()
        WHERE dedupe_key=$1 RETURNING updated""",
        str(job_id),
        manager_id,
    )
    return {"X-Job-ID": str(job_id), "X-Job-Manager": str(manager_id), "X-Job-Claimed-At": row["updated"].isoformat()}


@pytest.mark.parametrize("resend", [False, True])
async def test_Q11_Q12_partial_external_destinations_preserve_completed_result(queue_http, queue_db, resend):
    job_id = await held_job(queue_db)
    headers = await active_claim(queue_db, job_id)
    first = f"{BASE}/{job_id}/effects/first-destination"
    second = f"{BASE}/{job_id}/effects/second-destination"
    assert (await queue_http.post(first + "/claim", headers=headers, json={"destination": "one"})).json()[
        "state"
    ] == "claimed"
    await queue_db.execute("INSERT INTO business_effects(id,value) VALUES('first-external-destination',1)")
    complete = await queue_http.post(first + "/complete", headers=headers, json={"result": {"external_id": 123}})
    assert complete.status_code == 200
    assert (await queue_http.post(second + "/claim", headers=headers, json={"destination": "two"})).json()[
        "state"
    ] == "claimed"
    await queue_db.execute("UPDATE pgqueuer SET status='failed',queue_manager_id=NULL WHERE dedupe_key=$1", str(job_id))
    blocked = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
    assert blocked.json()["outcome"] == "requires_reconciliation"
    reconciliation = {"resend": True} if resend else {"result": {"external_id": 456}}
    resolved = await queue_http.post(
        second + "/reconcile",
        json={
            "expected_generation": 0,
            "operator_id": OPERATOR,
            "request_id": str(uuid4()),
            "reason": "External service history reconciled",
            **reconciliation,
        },
    )
    assert resolved.status_code == 200
    accepted = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
    assert accepted.json()["outcome"] == "queued"
    replay_headers = await active_claim(queue_db, job_id)
    preserved = await queue_http.post(first + "/claim", headers=replay_headers, json={"destination": "one"})
    assert preserved.json() == {"state": "completed", "result": {"external_id": 123}}
    recovered = await queue_http.post(second + "/claim", headers=replay_headers, json={"destination": "two"})
    assert recovered.json()["state"] == ("claimed" if resend else "completed")
    assert await queue_db.fetchval("SELECT value FROM business_effects WHERE id='first-external-destination'") == 1


async def test_Q09_snapshot_http_retains_first_reward_decision(queue_http, queue_db):
    job_id = await held_job(queue_db)
    headers = await active_claim(queue_db, job_id)
    path = f"{BASE}/{job_id}/snapshots/reward"
    first = await queue_http.post(path, headers=headers, json={"value": {"rank": 1}})
    second = await queue_http.post(path, headers=headers, json={"value": {"rank": 2}})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"value": {"rank": 1}}


async def test_Q17_stats_expose_pressure_and_held_uncertainty(queue_http, queue_db):
    job_id = await held_job(queue_db)
    await queue_db.execute(
        """INSERT INTO job_effects(job_id,effect_key,kind,state,fingerprint)
        VALUES($1,'uncertain','external','started','fingerprint')""",
        job_id,
    )
    response = await queue_http.get(f"{BASE}/stats", params={"operator_id": OPERATOR})
    assert response.status_code == 200
    assert response.json() == {
        "ready": 0,
        "delayed": 0,
        "processing": 0,
        "held": 1,
        "oldest_ready_age_seconds": None,
        "uncertain_effects": 1,
    }


async def test_Q17_alert_cursor_reaches_newer_work_without_acknowledging_failed_renders(queue_http, queue_db):
    jobs = {str(await held_job(queue_db)) for _ in range(101)}
    first = await queue_http.get(f"{BASE}/alerts")
    assert first.status_code == 200
    assert len(first.json()) == 100
    second = await queue_http.get(f"{BASE}/alerts", params={"after": first.json()[-1]["job_id"]})
    assert second.status_code == 200
    assert len(second.json()) == 1
    assert {job["job_id"] for job in first.json() + second.json()} == jobs
    # Advancing the read cursor is not a rendering acknowledgement: every failed
    # card is still pending and appears again after the supervisor wraps.
    wrapped = await queue_http.get(f"{BASE}/alerts")
    assert [job["job_id"] for job in wrapped.json()] == [job["job_id"] for job in first.json()]
    assert await queue_db.fetchval("SELECT count(*) FROM job_alerts WHERE rendered_status IS NOT NULL") == 0


@pytest.fixture
async def live_workers(queue_dsn, tmp_path):
    processes = []

    async def start(phase):
        marker = tmp_path / f"{uuid4().hex}.marker"
        log = marker.with_suffix(".log")
        if directory := os.getenv("QUEUE_ARTIFACT_DIR"):
            artifact = Path(directory) / log.name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            log.symlink_to(artifact)
        with log.open("wb") as output:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(Path(__file__).with_name("worker_process.py")),
                queue_dsn,
                str(marker),
                phase,
                stdout=output,
                stderr=output,
            )
        processes.append(process)
        return process

    try:
        yield start
    finally:
        for process in processes:
            await stop_live_worker(process)


async def stop_live_worker(process):
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            process.kill()
            await process.wait()


async def wait_for_http_state(client, job_id, status, generation):
    async with asyncio.timeout(12):
        while True:
            response = await client.get(f"{BASE}/{job_id}/operations", params={"operator_id": OPERATOR})
            assert response.status_code == 200
            job = response.json()
            if job["status"] == status and job["retry_generation"] == generation:
                return job
            await asyncio.sleep(0.025)


@pytest.mark.queue_fault
@pytest.mark.parametrize("scenario", ["concurrent", "lost_response", "second_failure"])
async def test_Q05_Q19_Q20_Q23_Q24_http_retry_after_partial_worker_failure(
    queue_http,
    queue_db,
    live_workers,
    response_fault,
    scenario,
):
    async with queue_db.transaction():
        public = await queue_store.enqueue_job(
            queue_db,
            event_name="completion.ocr.requested",
            event_key=str(uuid4()),
            payload={"submission": 1},
        )
    job_id = public.id
    identity = await queue_db.fetchrow("SELECT queue_job_id,event_key,payload FROM jobs WHERE id=$1", job_id)
    first_worker = await live_workers("fail_after_first")
    held = await wait_for_http_state(queue_http, job_id, "failed", 0)
    assert held["handler_failures"] == 3
    assert [(effect["effect_key"], effect["state"]) for effect in held["effects"]] == [("effect:1", "completed")]
    await stop_live_worker(first_worker)

    next_worker = await live_workers("fail_after_first" if scenario == "second_failure" else "run")
    payload = retry_request()
    if scenario == "lost_response":
        response_fault["drop_retry_response"] = True
        with pytest.raises(ConnectionResetError):
            await queue_http.post(f"{BASE}/{job_id}/retry", json=payload)
        assert response_fault["dropped_status"] == 200
        accepted = await queue_http.post(f"{BASE}/{job_id}/retry", json=payload)
    else:
        responses = await asyncio.gather(*(queue_http.post(f"{BASE}/{job_id}/retry", json=payload) for _ in range(2)))
        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json() == responses[1].json()
        accepted = responses[0]
    assert accepted.status_code == 200
    assert accepted.json()["outcome"] == "queued"
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 1

    expected_generation = 1
    if scenario == "second_failure":
        failed_again = await wait_for_http_state(queue_http, job_id, "failed", 1)
        assert failed_again["handler_failures"] == 3
        assert [(effect["effect_key"], effect["state"]) for effect in failed_again["effects"]] == [
            ("effect:1", "completed")
        ]
        stale = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request())
        assert stale.json()["outcome"] == "stale"
        assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == 1
        await stop_live_worker(next_worker)
        await live_workers("run")
        accepted = await queue_http.post(f"{BASE}/{job_id}/retry", json=retry_request(expected_generation=1))
        assert accepted.json()["outcome"] == "queued"
        expected_generation = 2

    completed = await wait_for_http_state(queue_http, job_id, "succeeded", expected_generation)
    assert [(effect["effect_key"], effect["state"]) for effect in completed["effects"]] == [
        ("effect:1", "completed"),
        ("effect:2", "completed"),
    ]
    assert identity == await queue_db.fetchrow("SELECT queue_job_id,event_key,payload FROM jobs WHERE id=$1", job_id)
    assert [row["value"] for row in await queue_db.fetch("SELECT value FROM business_effects ORDER BY id")] == [1, 1]
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", job_id) == expected_generation
