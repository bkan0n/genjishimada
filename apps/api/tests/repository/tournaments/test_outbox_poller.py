"""Integration tests for the tournament outbox poller (07-02).

``publish_pending_transitions(state)`` selects unpublished
``tournaments.pending_transitions`` rows under ``FOR UPDATE SKIP LOCKED`` inside
one transaction, builds each into its SDK event struct, publishes it via
``BaseService.publish_message``, and marks it published in the same transaction
(publish-then-mark = at-least-once, D-11).

The poller passes ``Headers({})`` to ``publish_message`` (production path), so to
exercise it in tests without a live RabbitMQ broker we stub
``TournamentOutboxService.publish_message`` -- the same effect as the documented
``X-PYTEST-ENABLED=1`` publish skip (base.py), but lets us assert call counts.
The publish-failure test needs no stub: the failure happens in ``_build_event``
(``msgspec.convert``) before publish, leaving the row unmarked.
"""

import datetime as dt
import json
from uuid import uuid4

import asyncpg
import msgspec
import pytest
from genjishimada_sdk.internal import JobStatusResponse
from litestar.datastructures import State

import services.tournament_outbox_service as outbox_module
from services.tournament_outbox_service import (
    _build_event,
    publish_pending_transitions,
)

pytestmark = [pytest.mark.domain_tournaments]

# The hardened repo query the poller relies on (asserted present per acceptance criteria).
_SKIP_LOCKED_SQL = "FOR UPDATE SKIP LOCKED"


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _started_payload(cycle_id: int, category_id: int, map_id: int) -> str:
    return json.dumps(
        {
            "cycle_id": cycle_id,
            "category_id": category_id,
            "map_id": map_id,
            "map_code": "ABC12",
            "map_name": "TestMap",
            "started_at": _now_iso(),
            "ends_at": _now_iso(),
        }
    )


def _completed_payload(cycle_id: int, category_id: int) -> str:
    return json.dumps(
        {
            "cycle_id": cycle_id,
            "category_id": category_id,
            "standings": [],
            "winner_user_id": None,
        }
    )


async def _seed_transition(pool: asyncpg.Pool, cycle_id: int, event_type: str, payload: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
            VALUES ($1, $2, $3::jsonb)
            RETURNING id
            """,
            cycle_id,
            event_type,
            payload,
        )


async def _published(pool: asyncpg.Pool, transition_id: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT published FROM tournaments.pending_transitions WHERE id = $1",
            transition_id,
        )


def _stub_publish(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace publish_message with a recorder; returns the list of recorded calls."""
    calls: list[dict] = []

    async def _fake_publish(self, *, routing_key, data, headers, idempotency_key=None):  # noqa: ANN001
        calls.append({"routing_key": routing_key, "data": data, "idempotency_key": idempotency_key})
        return JobStatusResponse(uuid4(), "succeeded")

    monkeypatch.setattr(outbox_module.TournamentOutboxService, "publish_message", _fake_publish)
    return calls


async def _make_cycle(create_test_category, create_test_cycle, create_test_map) -> tuple[int, int, int]:
    """Create a (category_id, map_id, cycle_id) for FK-valid outbox rows."""
    category_id = await create_test_category(cycle_frequency="weekly")
    map_id = await create_test_map(difficulty="Medium")
    cycle_id = await create_test_cycle(category_id, map_id, status="active", started_at=dt.datetime.now(dt.UTC))
    return category_id, map_id, cycle_id


class TestPublishAndMark:
    """The poller publishes unpublished rows and marks them published."""

    async def test_poller_publishes_and_marks(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """Two unpublished rows -> both published, both publish_message-d once each."""
        category_id, map_id, cycle_id = await _make_cycle(create_test_category, create_test_cycle, create_test_map)
        started = await _seed_transition(
            asyncpg_pool, cycle_id, "cycle_started", _started_payload(cycle_id, category_id, map_id)
        )
        completed = await _seed_transition(
            asyncpg_pool, cycle_id, "cycle_completed", _completed_payload(cycle_id, category_id)
        )

        calls = _stub_publish(monkeypatch)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        assert await _published(asyncpg_pool, started) is True
        assert await _published(asyncpg_pool, completed) is True
        # Our two rows were published with their cycle-scoped idempotency keys. The
        # shared DB may carry rows from other tests, so assert membership (subset),
        # not an exact total count.
        keys = [c["idempotency_key"] for c in calls]
        assert f"tournament:cycle_started:{cycle_id}" in keys
        assert f"tournament:cycle_completed:{cycle_id}" in keys
        # Each of our keys was published exactly once (no double-publish in one pass).
        assert keys.count(f"tournament:cycle_started:{cycle_id}") == 1
        assert keys.count(f"tournament:cycle_completed:{cycle_id}") == 1
        our_calls = {
            c["routing_key"]
            for c in calls
            if c["idempotency_key"] in {f"tournament:cycle_started:{cycle_id}", f"tournament:cycle_completed:{cycle_id}"}
        }
        assert our_calls == {"api.tournament.cycle_started", "api.tournament.cycle_completed"}


class TestSkipLocked:
    """FOR UPDATE SKIP LOCKED prevents a second poller from re-publishing locked rows."""

    async def test_skip_locked_no_double_publish(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """While connection A holds the unpublished rows, the poller processes zero rows."""
        category_id, map_id, cycle_id = await _make_cycle(create_test_category, create_test_cycle, create_test_map)
        completed = await _seed_transition(
            asyncpg_pool, cycle_id, "cycle_completed", _completed_payload(cycle_id, category_id)
        )

        calls = _stub_publish(monkeypatch)
        state = State({"db_pool": asyncpg_pool})

        conn_a = await asyncpg_pool.acquire()
        try:
            tx = conn_a.transaction()
            await tx.start()
            # Lock all unpublished rows on connection A.
            locked = await conn_a.fetch(
                f"""
                SELECT id FROM tournaments.pending_transitions
                WHERE published = FALSE
                ORDER BY created_at ASC
                {_SKIP_LOCKED_SQL}
                """
            )
            assert any(r["id"] == completed for r in locked)

            # The poller sees our row as skip-locked -> never publishes it, leaves it FALSE.
            our_key = f"tournament:cycle_completed:{cycle_id}"
            await publish_pending_transitions(state)
            assert our_key not in [c["idempotency_key"] for c in calls]
            assert await _published(asyncpg_pool, completed) is False

            await tx.rollback()
        finally:
            await asyncpg_pool.release(conn_a)

        # Lock released -> the poller now publishes and marks our row.
        await publish_pending_transitions(state)
        assert our_key in [c["idempotency_key"] for c in calls]
        assert await _published(asyncpg_pool, completed) is True


class TestPublishFailure:
    """A row whose payload fails msgspec.convert stays unpublished (at-least-once)."""

    async def test_publish_failure_leaves_unpublished(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A cycle_completed payload missing `standings` raises and is NOT marked published."""
        category_id, map_id, cycle_id = await _make_cycle(create_test_category, create_test_cycle, create_test_map)
        # Malformed: missing the required `standings` and `winner_user_id` keys.
        bad_payload = json.dumps({"cycle_id": cycle_id, "category_id": category_id})
        bad = await _seed_transition(asyncpg_pool, cycle_id, "cycle_completed", bad_payload)

        # Stub publish so any incidental well-formed row does not hit a real broker;
        # the whole batch rolls back when the bad row raises anyway.
        _stub_publish(monkeypatch)
        state = State({"db_pool": asyncpg_pool})

        # _build_event's msgspec.convert raises before any publish; the poller propagates it.
        with pytest.raises(msgspec.ValidationError):
            await publish_pending_transitions(state)

        # The offending row was never marked published (the mark never ran).
        assert await _published(asyncpg_pool, bad) is False


class TestCycleEndRewardHook:
    """The poller invokes cycle-end rewards + the reset sweep on cycle_completed rows (08-03)."""

    async def test_cycle_completed_invokes_award_cycle_end(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A cycle_completed row drives award_cycle_end with the built event + conn."""
        import services.tournament_reward_service as reward_module

        category_id, map_id, cycle_id = await _make_cycle(create_test_category, create_test_cycle, create_test_map)
        await _seed_transition(
            asyncpg_pool, cycle_id, "cycle_completed", _completed_payload(cycle_id, category_id)
        )

        # The xdist/session-shared DB may carry an orphaned unpublishable poison row
        # from TestPublishFailure that would make the poll raise before reaching our
        # row. Clear all still-unpublished rows first so this poll batch is just ours.
        async with asyncpg_pool.acquire() as _c:
            await _c.execute(
                "DELETE FROM tournaments.pending_transitions WHERE published = FALSE AND cycle_id <> $1",
                cycle_id,
            )

        _stub_publish(monkeypatch)
        captured: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            captured.append(event.cycle_id)

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        assert cycle_id in captured

    async def test_cycle_started_does_not_invoke_award_cycle_end(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A cycle_started row never invokes a reward call."""
        import services.tournament_reward_service as reward_module

        category_id, map_id, cycle_id = await _make_cycle(create_test_category, create_test_cycle, create_test_map)
        await _seed_transition(
            asyncpg_pool, cycle_id, "cycle_started", _started_payload(cycle_id, category_id, map_id)
        )

        # The xdist/session-shared DB may carry an orphaned unpublishable poison row
        # from TestPublishFailure that would make the poll raise before reaching our
        # row. Clear all still-unpublished rows first so this poll batch is just ours.
        async with asyncpg_pool.acquire() as _c:
            await _c.execute(
                "DELETE FROM tournaments.pending_transitions WHERE published = FALSE AND cycle_id <> $1",
                cycle_id,
            )

        _stub_publish(monkeypatch)
        captured: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            captured.append(event.cycle_id)

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        assert cycle_id not in captured


class TestBuildEvent:
    """_build_event rejects unknown event types (defense for the routing map)."""

    async def test_invalid_event_type_rejected(self):
        """An unknown event_type is not mappable to a routing key / struct."""
        row = {
            "event_type": "not_a_real_event",
            "cycle_id": 1,
            "payload": {},
        }
        with pytest.raises(KeyError):
            _build_event(row)
