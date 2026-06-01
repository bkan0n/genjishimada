"""Integration tests for the tournament outbox poller (07-02 / 12-03).

``publish_pending_transitions(state)`` selects unpublished
``tournaments.pending_transitions`` rows under ``FOR UPDATE SKIP LOCKED`` inside
one transaction, builds each ``edition_rollover`` row into ONE
``TournamentRolloverEvent``, publishes it on ``api.tournament.rollover`` with the
idempotency key ``tournament:rollover:{edition_id}`` (D-09/D-11), and marks it
published in the same transaction (publish-then-mark = at-least-once, D-11).

The reward side-effects (``award_cycle_end`` + the non-participant streak reset)
run ONCE PER CHILD CYCLE — i.e. once per ``event.results`` entry, keyed on
``entry.cycle_id`` (Pattern 4) — not once per edition.

The poller passes ``Headers({})`` to ``publish_message`` (production path), so to
exercise it in tests without a live RabbitMQ broker we stub
``TournamentOutboxService.publish_message`` -- the same effect as the documented
``X-PYTEST-ENABLED=1`` publish skip (base.py), but lets us assert call counts.
"""

import datetime as dt
import json
from uuid import uuid4

import asyncpg
import msgspec
import pytest
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.tournaments import TournamentRolloverEvent
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


def _started_entry(cycle_id: int, category_id: int, map_id: int) -> dict:
    return {
        "cycle_id": cycle_id,
        "category_id": category_id,
        "map_id": map_id,
        "map_code": "ABC12",
        "map_name": "TestMap",
        "started_at": _now_iso(),
        "ends_at": _now_iso(),
    }


def _completed_entry(cycle_id: int, category_id: int) -> dict:
    return {
        "cycle_id": cycle_id,
        "category_id": category_id,
        "standings": [],
        "winner_user_id": None,
    }


def _rollover_payload(edition_id: int, results: list[dict], started: list[dict]) -> str:
    return json.dumps({"edition_id": edition_id, "results": results, "started": started})


async def _seed_rollover(
    pool: asyncpg.Pool,
    edition_id: int,
    payload: str,
) -> int:
    """Seed ONE edition_rollover outbox row (cycle_id NULL, edition_id set)."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO tournaments.pending_transitions (cycle_id, edition_id, event_type, payload)
            VALUES (NULL, $1, 'edition_rollover', $2::jsonb)
            RETURNING id
            """,
            edition_id,
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


async def _clear_other_unpublished(pool: asyncpg.Pool, edition_id: int) -> None:
    """Clear unpublished rows from other tests so this poll batch is just ours.

    The xdist/session-shared DB may carry rows (including unpublishable poison
    rows) from sibling tests that would make the poll publish/raise on rows we
    do not own. Scope each poll to our edition.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM tournaments.pending_transitions WHERE published = FALSE AND edition_id IS DISTINCT FROM $1",
            edition_id,
        )


async def _make_edition_with_cycles(
    asyncpg_pool: asyncpg.Pool,
    create_test_category,
    create_test_edition,
    create_test_child_cycle,
    create_test_map,
    n: int = 1,
) -> tuple[int, list[tuple[int, int, int]]]:
    """Create an edition + n (category, map, child cycle) tuples for FK-valid rows."""
    started_at = dt.datetime.now(dt.UTC)
    ends_at = started_at + dt.timedelta(days=7)
    edition_id = await create_test_edition(started_at, ends_at)
    children: list[tuple[int, int, int]] = []
    for _ in range(n):
        category_id = await create_test_category()
        map_id = await create_test_map(difficulty="Medium")
        cycle_id = await create_test_child_cycle(edition_id, category_id, map_id, status="active")
        children.append((category_id, map_id, cycle_id))
    return edition_id, children


class TestRolloverPublish:
    """One edition_rollover row -> exactly ONE publish keyed by edition_id (D-09/D-11)."""

    async def test_one_row_one_publish_with_edition_idempotency_key(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """A single edition_rollover row publishes once on api.tournament.rollover."""
        edition_id, children = await _make_edition_with_cycles(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=2
        )
        (cat_a, map_a, cycle_a), (cat_b, map_b, cycle_b) = children
        payload = _rollover_payload(
            edition_id,
            results=[_completed_entry(cycle_a, cat_a), _completed_entry(cycle_b, cat_b)],
            started=[_started_entry(cycle_a, cat_a, map_a), _started_entry(cycle_b, cat_b, map_b)],
        )
        row_id = await _seed_rollover(asyncpg_pool, edition_id, payload)
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        # award_cycle_end touches xp ledger; stub it out for the publish-shape test.
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        assert await _published(asyncpg_pool, row_id) is True

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        call = our[0]
        assert call["routing_key"] == "api.tournament.rollover"
        assert isinstance(call["data"], TournamentRolloverEvent)
        assert call["data"].edition_id == edition_id
        assert {e.cycle_id for e in call["data"].results} == {cycle_a, cycle_b}
        assert {e.cycle_id for e in call["data"].started} == {cycle_a, cycle_b}


class TestRolloverIdempotentRepoll:
    """A crash before mark-published re-publishes with the SAME idempotency key (at-least-once)."""

    async def test_repoll_republishes_same_key(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """While conn A holds the row locked the poller skips it; once released it publishes once."""
        edition_id, children = await _make_edition_with_cycles(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        payload = _rollover_payload(
            edition_id,
            results=[_completed_entry(cycle_a, cat_a)],
            started=[_started_entry(cycle_a, cat_a, map_a)],
        )
        row_id = await _seed_rollover(asyncpg_pool, edition_id, payload)
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _noop_award)
        state = State({"db_pool": asyncpg_pool})
        key = f"tournament:rollover:{edition_id}"

        conn_a = await asyncpg_pool.acquire()
        try:
            tx = conn_a.transaction()
            await tx.start()
            locked = await conn_a.fetch(
                f"""
                SELECT id FROM tournaments.pending_transitions
                WHERE published = FALSE
                ORDER BY created_at ASC
                {_SKIP_LOCKED_SQL}
                """
            )
            assert any(r["id"] == row_id for r in locked)

            # Skip-locked -> never publishes our row, leaves it FALSE.
            await publish_pending_transitions(state)
            assert key not in [c["idempotency_key"] for c in calls]
            assert await _published(asyncpg_pool, row_id) is False

            await tx.rollback()
        finally:
            await asyncpg_pool.release(conn_a)

        # Lock released -> the poller publishes and marks our row, same key.
        await publish_pending_transitions(state)
        assert [c["idempotency_key"] for c in calls].count(key) == 1
        assert await _published(asyncpg_pool, row_id) is True


class TestRolloverRewardPerChildCycle:
    """award_cycle_end runs once PER results entry (per child cycle), not once per edition."""

    async def test_award_called_once_per_results_entry(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """A rollover with N results entries drives award_cycle_end N times, keyed on cycle_id."""
        edition_id, children = await _make_edition_with_cycles(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=3
        )
        results = [_completed_entry(c, cat) for (cat, _m, c) in children]
        started = [_started_entry(c, cat, m) for (cat, m, c) in children]
        payload = _rollover_payload(edition_id, results=results, started=started)
        await _seed_rollover(asyncpg_pool, edition_id, payload)
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        captured: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            captured.append(event.cycle_id)
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        expected = sorted(c for (_cat, _m, c) in children)
        assert sorted(captured) == expected  # once per child cycle, not once per edition


class TestRolloverHiatusSections:
    """Into-hiatus (results-only) and out-of-hiatus (started-only) each publish ONE event."""

    async def test_into_hiatus_results_only(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """results present, started empty -> one publish; started section empty."""
        edition_id, children = await _make_edition_with_cycles(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, _map_a, cycle_a) = children[0]
        payload = _rollover_payload(edition_id, results=[_completed_entry(cycle_a, cat_a)], started=[])
        row_id = await _seed_rollover(asyncpg_pool, edition_id, payload)
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        assert our[0]["data"].started == []
        assert len(our[0]["data"].results) == 1
        assert await _published(asyncpg_pool, row_id) is True

    async def test_out_of_hiatus_started_only(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """started present, results empty -> one publish; no reward calls; results empty."""
        edition_id, children = await _make_edition_with_cycles(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        payload = _rollover_payload(edition_id, results=[], started=[_started_entry(cycle_a, cat_a, map_a)])
        row_id = await _seed_rollover(asyncpg_pool, edition_id, payload)
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        captured: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            captured.append(event.cycle_id)
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_end", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        assert our[0]["data"].results == []
        assert len(our[0]["data"].started) == 1
        assert captured == []  # no results entries -> no reward calls
        assert await _published(asyncpg_pool, row_id) is True


class TestPublishFailure:
    """A row whose payload fails msgspec.convert stays unpublished (at-least-once)."""

    async def test_publish_failure_leaves_unpublished(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """An edition_rollover payload missing `started` raises and is NOT marked published."""
        edition_id, _children = await _make_edition_with_cycles(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        # Malformed: missing the required `started` key.
        bad_payload = json.dumps({"edition_id": edition_id, "results": []})
        bad = await _seed_rollover(asyncpg_pool, edition_id, bad_payload)
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        _stub_publish(monkeypatch)
        state = State({"db_pool": asyncpg_pool})

        # _build_event's msgspec.convert raises before any publish; the poller propagates it.
        with pytest.raises(msgspec.ValidationError):
            await publish_pending_transitions(state)

        assert await _published(asyncpg_pool, bad) is False


class TestPoolNotReady:
    """publish_pending_transitions no-ops cleanly when db_pool is absent (07-04)."""

    async def test_publish_noops_when_db_pool_absent(self, monkeypatch: pytest.MonkeyPatch):
        """With no db_pool in state the call returns normally and never publishes."""
        state = State({})  # empty -- no db_pool key
        calls = _stub_publish(monkeypatch)

        await publish_pending_transitions(state)

        assert calls == []


class TestBuildEvent:
    """_build_event rejects unknown event types (defense for the routing map)."""

    async def test_invalid_event_type_rejected(self):
        """An unknown event_type is not mappable to a routing key / struct."""
        row = {
            "event_type": "not_a_real_event",
            "cycle_id": None,
            "edition_id": 1,
            "payload": {},
        }
        with pytest.raises(KeyError):
            _build_event(row)

    async def test_rollover_event_type_builds_combined(self):
        """An edition_rollover row builds a TournamentRolloverEvent on the rollover key."""
        row = {
            "event_type": "edition_rollover",
            "cycle_id": None,
            "edition_id": 7,
            "payload": {"edition_id": 7, "results": [], "started": []},
        }
        routing_key, event = _build_event(row)
        assert routing_key == "api.tournament.rollover"
        assert isinstance(event, TournamentRolloverEvent)
        assert event.edition_id == 7
