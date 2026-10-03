"""Legacy work cannot restart until its prior effects are unambiguously absent."""

import asyncio
import json
from uuid import uuid4

import asyncpg
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


@pytest.mark.parametrize("identity", ["event_key", "job_id"])
@pytest.mark.parametrize("held_first", [True, False])
async def test_Q27_partial_duplicate_prevents_replay_of_logical_work(queue_db, tmp_path, identity, held_first):
    shared = {identity: str(uuid4())}
    if identity == "job_id":
        await queue_db.execute("INSERT INTO jobs(id,action) VALUES ($1,'api.completion.submission')", shared[identity])
    records = [
        reviewed_record(
            source_id="a-held" if held_first else "z-held", effects_started=True, legacy_claim=True, **shared
        ),
        reviewed_record(source_id="z-unstarted" if held_first else "a-unstarted", effects_started=False, **shared),
    ]
    manifest = tmp_path / "duplicates.jsonl"
    manifest.write_text("\n".join(json.dumps(record) for record in records))
    assert [plan.disposition for plan in importer().load_manifest(manifest)] == ["needs_reconciliation"] * 2
    # Direct callers must receive the same protection as the file loader.
    plans = [importer().plan_record(record, "unused") for record in records]
    assert await importer().apply_manifest(queue_db, plans) == {"needs_reconciliation": 2}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0


async def test_Q27_stored_history_protects_duplicate_without_original_job_id(queue_db):
    job_id = uuid4()
    await queue_db.execute(
        "INSERT INTO jobs(id,action,status) VALUES ($1,'api.completion.submission','failed')", job_id
    )
    plans = [
        importer().plan_record(
            reviewed_record(source_id=source_id, event_key="same-event", effects_started=False, **identity), "unused"
        )
        for source_id, identity in [("a-copy", {}), ("z-original", {"job_id": str(job_id)})]
    ]
    assert await importer().apply_manifest(queue_db, plans) == {"needs_reconciliation": 2}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0


async def test_Q27_partial_evidence_propagates_through_both_identity_types(queue_db):
    job_id = str(uuid4())
    records = [
        reviewed_record(source_id="c-partial", event_key="first", job_id=job_id, effects_started=True),
        reviewed_record(source_id="b-bridge", event_key="second", job_id=job_id, effects_started=False),
        reviewed_record(source_id="a-copy", event_key="second", effects_started=False),
    ]
    plans = [importer().plan_record(record, "unused") for record in records]
    assert await importer().apply_manifest(queue_db, plans) == {"needs_reconciliation": 3}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0


@pytest.mark.parametrize("identity", ["event_key", "job_id"])
async def test_Q27_concurrent_import_observes_previously_held_duplicate(queue_db, queue_dsn, identity):
    shared = {identity: str(uuid4())}
    held = importer().plan_record(reviewed_record(source_id="held", effects_started=True, **shared), "unused")
    candidate = importer().plan_record(
        reviewed_record(source_id="candidate", effects_started=False, **shared), "unused"
    )
    connection = await asyncpg.connect(queue_dsn)
    pending = None
    try:
        async with queue_db.transaction():
            assert await importer().apply_manifest(queue_db, [held]) == {"needs_reconciliation": 1}
            pending = asyncio.create_task(importer().apply_manifest(connection, [candidate]))
            completed, _ = await asyncio.wait({pending}, timeout=0.05)
            assert not completed, "A competing import must wait for the logical identity's recorded evidence"
        assert await asyncio.wait_for(pending, 3) == {"needs_reconciliation": 1}
        assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await connection.close()


@pytest.mark.parametrize("legacy_exists", [True, False], ids=["existing-job", "missing-job"])
@pytest.mark.parametrize("original_sorts_first", [True, False], ids=["original-first", "copy-first"])
@pytest.mark.parametrize("reverse_records", [True, False], ids=["reversed-manifest", "original-manifest"])
async def test_Q27_duplicate_import_preserves_identified_public_uuid(
    queue_db, tmp_path, legacy_exists, original_sorts_first, reverse_records
):
    job_id = uuid4()
    if legacy_exists:
        await queue_db.execute("INSERT INTO jobs(id,action) VALUES ($1,'api.completion.submission')", job_id)
    records = [
        reviewed_record(
            source_id="a-original" if original_sorts_first else "z-original",
            event_key="same-reviewed-event",
            effects_started=False,
            job_id=str(job_id),
        ),
        reviewed_record(
            source_id="z-copy" if original_sorts_first else "a-copy",
            event_key="same-reviewed-event",
            effects_started=False,
        ),
    ]
    if reverse_records:
        records.reverse()
    manifest = tmp_path / "duplicates.jsonl"
    manifest.write_text("\n".join(json.dumps(record) for record in records))
    plans = importer().load_manifest(manifest)
    assert await importer().apply_manifest(queue_db, plans) == {"enqueued": 2}
    assert await queue_db.fetchval("SELECT id FROM jobs") == job_id
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 1
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1
    imported = await queue_db.fetch("SELECT source_id,job_id,payload FROM job_imports ORDER BY source_id")
    assert {row["job_id"] for row in imported} == {job_id}
    assert [json.loads(row["payload"]) for row in imported] == sorted(records, key=lambda row: row["source_id"])
    # Replanning both copies individually must not change their stored evidence or identity.
    repeated = [importer().plan_record(record, "unused") for record in reversed(records)]
    assert await importer().apply_manifest(queue_db, repeated) == {"already_recorded": 2}
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1


@pytest.mark.parametrize("conflict", ["public-uuid", "event-key", "event-name", "connected-identities"])
async def test_Q27_conflicting_duplicate_identities_remain_preserved(queue_db, tmp_path, conflict):
    first_id, second_id = str(uuid4()), str(uuid4())
    identities = [{"job_id": first_id, "event_key": "first-event"}]
    if conflict == "public-uuid":
        identities.append({"job_id": second_id, "event_key": "first-event"})
    elif conflict == "event-key":
        identities.append({"job_id": first_id, "event_key": "second-event"})
    elif conflict == "event-name":
        identities.append(
            {
                "job_id": first_id,
                "event_key": "first-event",
                "queue": "api.newsfeed.create",
                "payload": {"newsfeed_id": 8},
            }
        )
    else:
        identities.extend(
            [
                {"job_id": first_id, "event_key": "second-event"},
                {"job_id": second_id, "event_key": "second-event"},
                {"event_key": "first-event"},
            ]
        )
    records = [
        reviewed_record(source_id=f"source-{index}", effects_started=False, **identity)
        for index, identity in enumerate(identities)
    ]
    manifest = tmp_path / "conflicting-identities.jsonl"
    manifest.write_text("\n".join(json.dumps(record) for record in reversed(records)))
    assert {plan.disposition for plan in importer().load_manifest(manifest)} == {"needs_reconciliation"}
    # Apply must enforce the same safeguards without relying on load_manifest.
    plans = [importer().plan_record(record, "unused") for record in records]
    assert await importer().apply_manifest(queue_db, plans) == {"needs_reconciliation": len(records)}
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 0
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    imported = await queue_db.fetch("SELECT payload FROM job_imports ORDER BY source_id")
    assert [json.loads(row["payload"]) for row in imported] == records
    assert await importer().apply_manifest(queue_db, plans) == {"already_recorded": len(records)}


@pytest.mark.parametrize("legacy_exists", [True, False], ids=["existing-job", "missing-job"])
async def test_Q27_import_cannot_replace_supplied_uuid_with_existing_event_identity(queue_db, legacy_exists):
    previous = reviewed_record(source_id="previous-copy", event_key="same-event", effects_started=False)
    await importer().apply_manifest(queue_db, [importer().plan_record(previous, "unused")])
    existing_id = await queue_db.fetchval("SELECT id FROM jobs")
    supplied_id = uuid4()
    if legacy_exists:
        await queue_db.execute("INSERT INTO jobs(id,action) VALUES ($1,'api.completion.submission')", supplied_id)
    before = [dict(row) for row in await queue_db.fetch("SELECT * FROM jobs ORDER BY id")]
    record = reviewed_record(
        source_id="identified-copy",
        event_key="same-event",
        job_id=str(supplied_id),
        effects_started=False,
    )
    plans = [importer().plan_record(record, "unused")]
    assert await importer().apply_manifest(queue_db, plans) == {"needs_reconciliation": 1}
    assert [dict(row) for row in await queue_db.fetch("SELECT * FROM jobs ORDER BY id")] == before
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1
    imported = await queue_db.fetchrow("SELECT job_id,payload FROM job_imports WHERE source_id='identified-copy'")
    assert imported["job_id"] == (supplied_id if legacy_exists else None)
    assert imported["job_id"] != existing_id
    assert json.loads(imported["payload"]) == record
    assert await importer().apply_manifest(queue_db, plans) == {"already_recorded": 1}


@pytest.mark.parametrize("disposition", [[], {}], ids=["list", "object"])
async def test_Q27_nonstring_disposition_is_preserved_during_dry_run_and_apply(
    queue_db, tmp_path, monkeypatch, capsys, disposition
):
    record = reviewed_record(disposition=disposition, effects_started=False)
    manifest = tmp_path / "invalid-disposition.jsonl"
    manifest.write_text(json.dumps(record))
    monkeypatch.setattr("sys.argv", ["import_queue_backlog.py", str(manifest)])
    await importer().main()
    assert json.loads(capsys.readouterr().out) == {
        "mode": "dry-run",
        "source_records": 1,
        "dispositions": {"needs_reconciliation": 1},
    }
    plans = importer().load_manifest(manifest)
    assert await importer().apply_manifest(queue_db, plans) == {"needs_reconciliation": 1}
    assert json.loads(await queue_db.fetchval("SELECT payload FROM job_imports")) == record
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    assert await importer().apply_manifest(queue_db, plans) == {"already_recorded": 1}
