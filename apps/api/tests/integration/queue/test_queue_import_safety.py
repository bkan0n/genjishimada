"""Legacy work cannot restart until its prior effects are unambiguously absent."""

from uuid import uuid4

import pytest

from tests.integration.queue.test_queue_operations import importer

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


def reviewed_record(**changes):
    return {
        "source_id": "reviewed-import",
        "queue": "api.completion.submission",
        "payload": {"completion_id": 8},
        "disposition": "enqueue",
        "evidence": "Inspected the retained source and domain state.",
        **changes,
    }


@pytest.mark.parametrize(
    "history",
    [
        {},
        {"effects_started": True},
        {"effects_started": "false"},
        {"effects_started": False, "legacy_claim": True, "effects_reconciled": True},
        {"effects_started": False, "completed_effects": [{"message_id": 123}]},
    ],
    ids=["unknown", "partial-effects", "invalid-evidence", "legacy-claim", "completed-effect"],
)
async def test_Q27_ambiguous_or_partial_imports_remain_held(history):
    plan = importer().plan_record(reviewed_record(**history), "unused")
    assert plan.disposition == "needs_reconciliation"


async def test_Q27_explicitly_unstarted_import_can_be_enqueued(queue_db):
    plan = importer().plan_record(reviewed_record(effects_started=False), "unused")
    assert plan.disposition == "enqueued"
    assert await importer().apply_manifest(queue_db, [plan]) == {"enqueued": 1}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1


@pytest.mark.parametrize("status,attempts", [("processing", 0), ("failed", 0), ("queued", 1)])
async def test_Q27_persisted_execution_evidence_overrides_manifest_claim(queue_db, status, attempts):
    job_id = uuid4()
    await queue_db.execute(
        "INSERT INTO jobs(id,action,status,attempts) VALUES ($1,'api.completion.submission',$2,$3)",
        job_id,
        status,
        attempts,
    )
    plan = importer().plan_record(reviewed_record(job_id=str(job_id), effects_started=False), "unused")
    counts = await importer().apply_manifest(queue_db, [plan])
    assert counts == {"needs_reconciliation": 1}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    assert await queue_db.fetchval("SELECT status::text FROM jobs WHERE id=$1", job_id) == status
    assert await queue_db.fetchval("SELECT job_id FROM job_imports") == job_id
    assert await importer().apply_manifest(queue_db, [plan]) == {"already_recorded": 1}


@pytest.mark.parametrize("timestamp", ["started_at", "finished_at"])
async def test_Q27_queued_legacy_job_with_execution_timestamp_remains_held(queue_db, timestamp):
    job_id = uuid4()
    await queue_db.execute(
        f"INSERT INTO jobs(id,action,{timestamp}) VALUES ($1,'api.completion.submission',now())",
        job_id,
    )
    plan = importer().plan_record(reviewed_record(job_id=str(job_id), effects_started=False), "unused")
    assert await importer().apply_manifest(queue_db, [plan]) == {"needs_reconciliation": 1}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    assert await queue_db.fetchval(f"SELECT {timestamp} FROM jobs WHERE id=$1", job_id) is not None


async def test_Q27_held_import_preserves_missing_original_identity_without_creating_job(queue_db):
    missing_id = str(uuid4())
    plan = importer().plan_record(reviewed_record(job_id=missing_id, effects_started=True), "unused")
    assert await importer().apply_manifest(queue_db, [plan]) == {"needs_reconciliation": 1}
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 0
    assert await queue_db.fetchval("SELECT payload->>'job_id' FROM job_imports") == missing_id


async def test_Q27_partial_effects_are_preserved_without_replay(queue_db):
    await queue_db.execute("INSERT INTO business_effects VALUES ('xp',50)")
    plan = importer().plan_record(
        reviewed_record(
            legacy_claim=True,
            effects_reconciled=True,
            effects_started=True,
            evidence="Message 123 and 50 XP already completed; cleanup remains unfinished.",
        ),
        "unused",
    )
    assert await importer().apply_manifest(queue_db, [plan]) == {"needs_reconciliation": 1}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    assert await queue_db.fetchval("SELECT value FROM business_effects WHERE id='xp'") == 50
