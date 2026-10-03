"""Transport contracts and owner inventory; no Discord behavior or client involved."""

import ast
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import msgspec
import pytest
from genjishimada_sdk.queue import ALL_ENTRYPOINTS, API_ENTRYPOINTS, BOT_ENTRYPOINTS, EVENT_PAYLOAD_TYPES, JobEnvelope
from genjishimada_sdk.queue_store import enqueue_job
from genjishimada_sdk.queue_worker import FencedQueries
from pgqueuer.ports.repository import EntrypointExecutionParameter

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]
ROOT = Path(__file__).resolve().parents[5]


def example(schema, definitions):
    if "$ref" in schema:
        return example(definitions[schema["$ref"].rsplit("/", 1)[1]], definitions)
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return example(schema["anyOf"][0], definitions)
    kind = schema.get("type")
    if kind == "object":
        return {
            key: (
                "2026-01-01T00:00:00Z"
                if key in {"started_at", "ends_at"}
                else example(schema["properties"][key], definitions)
            )
            for key in schema.get("required", [])
        }
    if kind == "array":
        return [example(schema["items"], definitions)]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if kind == "string":
        if schema.get("format") == "date-time":
            return "2026-01-01T00:00:00Z"
        return "ABC123" if schema.get("maxLength") == 6 else "example"
    return None


async def test_Q26_all_event_payloads_cross_enqueue_and_typed_dispatch_boundaries(queue_db):
    registrations = {}
    for path in (ROOT / "apps/bot/extensions").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    not isinstance(decorator, ast.Call)
                    or not isinstance(decorator.func, ast.Name)
                    or decorator.func.id != "queue_consumer"
                ):
                    continue
                name = ast.literal_eval(decorator.args[0])
                assert name not in registrations, f"duplicate event {name}"
                struct = next(k.value for k in decorator.keywords if k.arg == "struct_type")
                registrations[name] = struct.id if isinstance(struct, ast.Name) else struct.attr
    assert len(registrations) == 21
    assert set(registrations) == BOT_ENTRYPOINTS
    assert len(API_ENTRYPOINTS) == 3
    for name, struct in registrations.items():
        assert struct == EVENT_PAYLOAD_TYPES[name].__name__
    for event_name in ALL_ENTRYPOINTS:
        payload_type = EVENT_PAYLOAD_TYPES[event_name]
        if payload_type is dict:
            payload = {"sample": "continuation"}
        else:
            schema = msgspec.json.schema(payload_type)
            payload = msgspec.convert(example(schema, schema.get("$defs", {})), type=payload_type)
        async with queue_db.transaction():
            public = await enqueue_job(queue_db, event_name=event_name, payload=payload, event_key=str(uuid4()))
        queries = FencedQueries.from_asyncpg_connection(queue_db)
        claimed = await queries.dequeue(
            1, {event_name: EntrypointExecutionParameter(1)}, uuid4(), 2, timedelta(seconds=60)
        )
        assert len(claimed) == 1
        envelope = msgspec.json.decode(claimed[0].payload, type=JobEnvelope)
        assert envelope.job_id == public.id and envelope.event_name == event_name
        decoded = msgspec.json.decode(envelope.payload, type=payload_type)
        assert decoded == payload
        await queries.log_jobs([(claimed[0], "successful", None)])
