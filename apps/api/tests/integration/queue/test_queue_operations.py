"""Reviewed backlog import, retention, operator tooling, and broker removal."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys
import tomllib
from uuid import uuid4

import pytest
import yaml

from genjishimada_sdk.queue_store import enqueue_job

ROOT = Path(__file__).resolve().parents[5]
pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


def importer():
    name = "queue_backlog_importer_for_tests"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/import_queue_backlog.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


async def test_Q27_import_replays_once_and_preserves_every_disposition(queue_db, tmp_path):
    records = [
        {
            "source_id": "normal",
            "queue": "api.completion.submission",
            "payload": {"completion_id": 1},
            "event_key": "completion:1",
            "disposition": "enqueue",
            "evidence": "Synthetic review: no prior effect",
        },
        {
            "source_id": "duplicate-copy",
            "queue": "api.completion.submission.dlq",
            "payload": {"completion_id": 1},
            "event_key": "completion:1",
            "disposition": "enqueue",
            "evidence": "Synthetic review: duplicate source copy",
        },
        {
            "source_id": "retired",
            "queue": "api.tournament.cycle_started",
            "payload": {},
            "disposition": "enqueue",
            "evidence": "Unrecognized old event",
        },
        {
            "source_id": "invalid",
            "queue": "api.completion.submission",
            "payload": {"completion_id": "invalid"},
            "disposition": "enqueue",
            "evidence": "Invalid schema",
        },
        {
            "source_id": "claimed",
            "queue": "api.completion.submission",
            "payload": {"completion_id": 2},
            "legacy_claim": True,
            "disposition": "enqueue",
            "evidence": "Old claim has no completion evidence",
        },
        {
            "source_id": "done",
            "queue": "api.completion.submission",
            "payload": {"completion_id": 3},
            "disposition": "completed",
            "evidence": "Synthetic completed effect evidence",
        },
        {
            "source_id": "discard",
            "queue": "unknown",
            "payload": {},
            "disposition": "discarded",
            "evidence": "Reviewed canceled source operation",
        },
    ]
    manifest = tmp_path / "reviewed.jsonl"
    manifest.write_text("\n".join(json.dumps(record) for record in records) + "\nmalformed legacy JSON\n")
    plans = importer().load_manifest(manifest)
    first = await importer().apply_manifest(queue_db, plans)
    assert first == {"enqueued": 2, "needs_reconciliation": 4, "completed": 1, "discarded": 1}
    again = await importer().apply_manifest(queue_db, importer().load_manifest(manifest))
    assert again == {"already_recorded": 8}
    assert await queue_db.fetchval("SELECT count(*) FROM job_imports") == 8
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 1
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1
    assert await queue_db.fetchval("SELECT count(DISTINCT job_id) FROM job_imports WHERE disposition='enqueued'") == 1
    assert await queue_db.fetchval("SELECT payload::text FROM job_imports WHERE source_id='claimed'")
    assert (
        await queue_db.fetchval(
            "SELECT payload->>'malformed_source' FROM job_imports WHERE payload ? 'malformed_source'"
        )
        == "malformed legacy JSON"
    )


async def test_Q27_import_preserves_existing_public_job_uuid(queue_db):
    legacy_id = uuid4()
    await queue_db.execute(
        "INSERT INTO jobs(id,action,status) VALUES($1,'api.completion.submission','failed')", legacy_id
    )
    plan = importer().plan_record(
        {
            "source_id": "legacy-public-id",
            "queue": "api.completion.submission",
            "payload": {"completion_id": 8},
            "job_id": str(legacy_id),
            "disposition": "enqueue",
            "evidence": "Synthetic reconciliation of legacy failed job",
        },
        "unused",
    )
    await importer().apply_manifest(queue_db, [plan])
    await importer().apply_manifest(queue_db, [plan])
    row = await queue_db.fetchrow("SELECT * FROM jobs WHERE id=$1", legacy_id)
    assert row["queue_job_id"] is not None
    assert row["status"] == "queued"
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 1
    assert await queue_db.fetchval("SELECT job_id FROM job_imports WHERE source_id='legacy-public-id'") == legacy_id


async def test_Q27_conflicting_import_rolls_back_all_new_dispositions(queue_db):
    baseline = {
        "source_id": "z-existing",
        "queue": "api.completion.submission",
        "payload": {"completion_id": 1},
        "disposition": "enqueue",
        "evidence": "Reviewed",
    }
    await importer().apply_manifest(queue_db, [importer().plan_record(baseline, "unused")])
    changed = {**baseline, "payload": {"completion_id": 2}}
    fresh = {**baseline, "source_id": "a-new", "payload": {"completion_id": 3}}
    with pytest.raises(ValueError, match="different recorded"):
        await importer().apply_manifest(
            queue_db, [importer().plan_record(fresh, "unused"), importer().plan_record(changed, "unused")]
        )
    assert await queue_db.fetchval("SELECT count(*) FROM job_imports") == 1
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 1
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1


async def test_Q28_runtime_dependencies_and_compose_have_no_broker():
    retired = {"aio-pika", "aiormq", "pamqp"}
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    names = {package["name"] for package in lock["package"]}
    assert not retired & names
    assert next(package["version"] for package in lock["package"] if package["name"] == "pgqueuer") == "1.1.1"
    for application in ["api", "bot"]:
        manifest = tomllib.loads((ROOT / f"apps/{application}/pyproject.toml").read_text())
        assert "pgqueuer==1.1.1" in manifest["project"]["dependencies"]
        for source in (ROOT / "apps" / application).rglob("*.py"):
            if "tests" in source.parts or source.name == "conftest.py":
                continue
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                assert not any(module.split(".")[0] in {"aio_pika", "aiormq", "pamqp"} for module in modules), source
    for filename in ["docker-compose.local.yml", "docker-compose.dev.yml", "docker-compose.prod.yml"]:
        compose = yaml.safe_load((ROOT / filename).read_text())
        assert not any("rabbit" in name.lower() for name in compose["services"])
        assert not any("rabbit" in name.lower() for name in compose.get("volumes", {}))
        for name, service in compose["services"].items():
            assert set(service.get("depends_on", {})) <= compose["services"].keys()
            assert not any(key.startswith("RABBITMQ_") for key in service.get("environment", {}))
            if "genjishimada-bot" in name:
                assert "QUEUE_DATABASE_URL" in service["environment"]
                assert service["stop_grace_period"] == "45s"
    assert not (ROOT / "infra/rabbitmq").exists()


@pytest.mark.parametrize(
    ("action", "status", "error"),
    [("api.completion.submission", "succeeded", "completed"), ("api.newsfeed.create", "failed", "action")],
    ids=["completed-legacy-job", "wrong-event-identity"],
)
async def test_Q27_import_cannot_repurpose_or_replay_completed_legacy_job(queue_db, action, status, error):
    legacy_id = uuid4()
    await queue_db.execute("INSERT INTO jobs(id,action,status) VALUES($1,$2,$3)", legacy_id, action, status)
    plan = importer().plan_record(
        {
            "source_id": "conflicting-legacy",
            "queue": "api.completion.submission",
            "payload": {"completion_id": 8},
            "job_id": str(legacy_id),
            "disposition": "enqueue",
            "evidence": "Synthetic review cannot override completed identity",
        },
        "unused",
    )
    with pytest.raises(ValueError, match=error):
        await importer().apply_manifest(queue_db, [plan])
    assert await queue_db.fetchval("SELECT count(*) FROM job_imports") == 0
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    row = await queue_db.fetchrow("SELECT * FROM jobs WHERE id=$1", legacy_id)
    assert row["status"] == status
    assert row["action"] == action
    assert row["queue_job_id"] is None


def maintenance():
    name = "queue_maintenance_for_tests"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "apps/api/utilities/queue_maintenance.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


async def seed_retention_job(conn, name, *, age_days=31, status="succeeded", active=False, uncertain=False):
    async with conn.transaction():
        job = await enqueue_job(
            conn, event_name="api.completion.submission", payload={"completion_id": 1}, event_key=name
        )
    number = await conn.fetchval("SELECT queue_job_id FROM jobs WHERE id=$1", job.id)
    await conn.execute(
        "UPDATE pgqueuer_log SET created=now()-make_interval(days=>$2) WHERE job_id=$1", number, age_days + 1
    )
    if not active:
        await conn.execute("DELETE FROM pgqueuer WHERE id=$1", number)
    await conn.execute(
        """INSERT INTO pgqueuer_log(created,job_id,status,priority,entrypoint)
           VALUES(now()-make_interval(days=>$2),$1,'successful',0,'api.completion.submission')""",
        number,
        age_days,
    )
    await conn.execute(
        "UPDATE jobs SET status=$2,finished_at=now()-make_interval(days=>$3),attempts=4,handler_failures=2 WHERE id=$1",
        job.id,
        status,
        age_days,
    )
    await conn.execute(
        """INSERT INTO job_effects(job_id,effect_key,kind,state,fingerprint,result)
           VALUES($1,'mutation','mutation','completed','stable','{"value":1}'::jsonb)""",
        job.id,
    )
    if uncertain:
        await conn.execute(
            """INSERT INTO job_effects(job_id,effect_key,kind,state,fingerprint,destination)
               VALUES($1,'uncertain','external','started','stable','test-recorder')""",
            job.id,
        )
    return job.id, number


async def test_Q16_log_retention_preserves_summaries_effects_and_nonterminal_work(queue_db):
    old, old_number = await seed_retention_job(queue_db, "old-success")
    recent, _ = await seed_retention_job(queue_db, "recent-success", age_days=29)
    held, _ = await seed_retention_job(queue_db, "held", status="failed", active=True)
    active, _ = await seed_retention_job(queue_db, "active-with-stale-summary", active=True)
    uncertain, _ = await seed_retention_job(queue_db, "uncertain", uncertain=True)
    retrying, _ = await seed_retention_job(queue_db, "retrying", status="queued", active=True)
    dependency, _ = await seed_retention_job(queue_db, "dependency-blocked", status="failed", active=True)
    await queue_db.execute("UPDATE jobs SET error_code='dependency_failed' WHERE id=$1", dependency)
    await queue_db.execute(
        """INSERT INTO pgqueuer_log(created,job_id,status,priority,entrypoint)
           VALUES(now()-interval '32 days',$1,'exception',0,'api.completion.submission')""",
        old_number,
    )
    await queue_db.execute(
        "INSERT INTO job_alerts(job_id,guild_id,channel_id,message_id) VALUES($1,11,22,33)",
        old,
    )
    await queue_db.execute(
        """INSERT INTO job_operations(request_id,job_id,operator_id,action,generation,reason,result)
           VALUES('saved-action',$1,141372217677053952,'retry',0,'retained evidence','{}')""",
        old,
    )
    before = dict(await queue_db.fetchrow("SELECT * FROM jobs WHERE id=$1", old))
    assert await maintenance().prune_completed_job_logs(queue_db) == 3
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer_log WHERE job_id=$1", old_number) == 0
    assert dict(await queue_db.fetchrow("SELECT * FROM jobs WHERE id=$1", old)) == before
    assert await queue_db.fetchval("SELECT count(*) FROM job_effects WHERE job_id=$1", old) == 1
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE job_id=$1", old) == 1
    assert await queue_db.fetchval("SELECT message_id FROM job_alerts WHERE job_id=$1", old) == 33
    for retained in [recent, held, active, uncertain, retrying, dependency]:
        assert (
            await queue_db.fetchval(
                "SELECT count(*) FROM pgqueuer_log l JOIN jobs j ON j.queue_job_id=l.job_id WHERE j.id=$1",
                retained,
            )
            == 2
        )
    assert await maintenance().prune_completed_job_logs(queue_db) == 0


async def test_Q16_log_retention_is_bounded_and_rollback_preserves_logs(queue_db):
    await seed_retention_job(queue_db, "one")
    await seed_retention_job(queue_db, "two")
    with pytest.raises(RuntimeError, match="rollback"):
        async with queue_db.transaction():
            assert await maintenance().prune_completed_job_logs(queue_db, batch_size=1) == 2
            raise RuntimeError("rollback")
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer_log") == 4
    assert await maintenance().prune_completed_job_logs(queue_db, batch_size=1) == 2
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer_log") == 2
    assert await maintenance().prune_completed_job_logs(queue_db, batch_size=1) == 2
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 2
    assert await queue_db.fetchval("SELECT count(*) FROM job_effects") == 2


def operator_cli():
    name = "queue_operator_cli_for_tests"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/queue_jobs.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


async def test_Q20_operator_cli_preserves_generation_and_request_id_after_lost_response(capsys):
    import httpx

    cli = operator_cli()
    job = uuid4()
    args = cli.parser().parse_args(["retry", str(job), "--generation", "6", "--request-id", "saved-request"])
    request = cli.operation(args, 141372217677053952)
    attempts = []

    def transport(message):
        attempts.append(message)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("Synthetic response loss", request=message)
        return httpx.Response(200, json={"job_id": str(job), "status": "queued", "retry_generation": 7})

    with httpx.Client(
        base_url="https://example.invalid",
        headers={"X-API-KEY": "test-secret-never-log"},
        transport=httpx.MockTransport(transport),
    ) as client:
        assert cli.execute(client, request) == 1
        assert cli.execute(client, request) == 0
    assert len(attempts) == 2
    for attempt in attempts:
        assert attempt.method == "POST"
        assert attempt.url.path == f"/api/v3/internal/jobs/{job}/retry"
        assert attempt.headers["X-API-KEY"] == "test-secret-never-log"
        assert json.loads(attempt.content) == {
            "operator_id": 141372217677053952,
            "expected_generation": 6,
            "request_id": "saved-request",
        }
    output = capsys.readouterr()
    assert "Request ID: saved-request" in output.err
    assert "test-secret-never-log" not in output.out + output.err


async def test_Q22_operator_cli_reconciliation_encodes_effect_key_and_requires_object_result(tmp_path):
    import httpx

    cli = operator_cli()
    job = uuid4()
    result = tmp_path / "result.json"
    result.write_text('{"message_id":123}')
    args = cli.parser().parse_args(
        [
            "reconcile",
            str(job),
            "channel:123/thread:456",
            "--generation",
            "4",
            "--result-file",
            str(result),
            "--reason",
            "Confirmed the existing delivery",
            "--request-id",
            "reconcile-once",
        ]
    )
    operation = cli.operation(args, 141372217677053952)
    request = httpx.Request(operation.method, "https://example.invalid" + operation.path, json=operation.body)
    assert b"channel%3A123%2Fthread%3A456" in request.url.raw_path
    assert operation.body["result"] == {"message_id": 123}
    assert operation.body["resend"] is False
    assert operation.body["expected_generation"] == 4
    result.write_text("null")
    with pytest.raises(ValueError, match="JSON object"):
        cli.operation(args, 141372217677053952)


@pytest.mark.parametrize("command", ["reconcile", "discard"])
async def test_Q22_operator_cli_requires_inspected_generation(command):
    cli = operator_cli()
    arguments = [command, str(uuid4()), "--reason", "Diagnosed current failure", "--request-id", "same-request"]
    if command == "reconcile":
        arguments.extend(["effect", "--resend"])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(arguments)
    args = cli.parser().parse_args([*arguments, "--generation", "5"])
    request = cli.operation(args, 141372217677053952)
    assert request.body["expected_generation"] == 5
    assert request.body["request_id"] == "same-request"
