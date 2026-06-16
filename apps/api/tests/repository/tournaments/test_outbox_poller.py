"""Integration tests for the tournament outbox poller (07-02 / 12-03).

``publish_pending_transitions(state)`` selects unpublished
``tournaments.pending_transitions`` rows under ``FOR UPDATE SKIP LOCKED`` inside
one transaction, builds each ``edition_rollover`` row into ONE
``TournamentRolloverEvent``, publishes it on ``api.tournament.rollover`` with the
START-qualified idempotency key ``tournament:rollover:{edition_id}:start`` (every
outbox rollover row is a bootstrap START; the edition END is published directly by
``process_awaiting_results_editions`` under the un-suffixed key), and marks it
published in the same transaction (publish-then-mark = at-least-once, D-11).

The reward side-effects (``award_cycle_placements`` per cycle + ``award_edition_streaks`` per edition)
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
from genjishimada_sdk.tournaments import TournamentEditionResultsEvent, TournamentRolloverEvent
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
        # award_cycle_placements touches xp ledger; stub it out for the publish-shape test.
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        assert await _published(asyncpg_pool, row_id) is True

        key = f"tournament:rollover:{edition_id}:start"
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

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})
        key = f"tournament:rollover:{edition_id}:start"

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
    """award_cycle_placements runs once PER results entry (per child cycle), not once per edition."""

    async def test_award_called_once_per_results_entry(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """A rollover with N results entries drives award_cycle_placements N times, keyed on cycle_id."""
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

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _fake_award)
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

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}:start"
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

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}:start"
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

    async def test_results_event_type_builds_results_only(self):
        """An edition_results row builds a TournamentEditionResultsEvent on the results key."""
        row = {
            "event_type": "edition_results",
            "cycle_id": None,
            "edition_id": 9,
            "payload": {"edition_id": 9, "results": []},
        }
        routing_key, event = _build_event(row)
        assert routing_key == "api.tournament.results"
        assert isinstance(event, TournamentEditionResultsEvent)
        assert event.edition_id == 9


# =============================================================================
# Plan 12.1-04: poller-owned drain state machine (D-01/D-02/D-05/D-07)
# =============================================================================
#
# The cron (12.1-01) is timing-only: it flips the due edition to
# 'awaiting_results', child cycles to 'finalizing', and writes NO outbox row. The
# poller now OWNS results computation: process_awaiting_results_editions runs
# inside the same publish-before-mark transaction and, per edition, branches on
# count_inflight_verifications:
#   * first tick, pending == 0 -> combined TournamentRolloverEvent
#     (results_pending=False), grant XP, edition + cycles -> completed
#   * first tick, pending  > 0 -> start-only TournamentRolloverEvent
#     (results_pending=True), set start_announced, NO grants, edition stays
#     awaiting_results (champion role held: empty results -> bot skips transfer)
#   * later tick, start_announced, pending == 0 (drained) -> write an
#     edition_results outbox row; the SAME loop drains it next tick at
#     tournament:results:{edition_id}, grants XP, edition + cycles -> completed


async def _set_edition_status(pool: asyncpg.Pool, edition_id: int, status: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tournaments.editions SET status = $2 WHERE id = $1",
            edition_id,
            status,
        )


async def _set_cycles_status(pool: asyncpg.Pool, edition_id: int, status: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tournaments.cycles SET status = $2 WHERE edition_id = $1",
            edition_id,
            status,
        )


async def _edition_row(pool: asyncpg.Pool, edition_id: int) -> dict:
    async with pool.acquire() as conn:
        return dict(await conn.fetchrow("SELECT * FROM tournaments.editions WHERE id = $1", edition_id))


async def _cycle_statuses(pool: asyncpg.Pool, edition_id: int) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status FROM tournaments.cycles WHERE edition_id = $1 ORDER BY id",
            edition_id,
        )
        return [r["status"] for r in rows]


async def _results_rows(pool: asyncpg.Pool, edition_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM tournaments.pending_transitions
            WHERE event_type = 'edition_results' AND edition_id = $1
            ORDER BY id
            """,
            edition_id,
        )
        return [dict(r) for r in rows]


async def _seed_completion(
    pool: asyncpg.Pool,
    cycle_id: int,
    user_id: int,
    map_id: int,
    status: str,
    time: float = 30.0,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            -- `completion` is a STORED generated column (migration 0029, video IS NOT NULL);
            -- it cannot be inserted. No video here -> completion is FALSE, as before.
            INSERT INTO tournaments.completions (cycle_id, user_id, map_id, time, screenshot, status)
            VALUES ($1, $2, $3, $4, 'https://x/s.png', $5)
            RETURNING id
            """,
            cycle_id,
            user_id,
            map_id,
            time,
            status,
        )


async def _make_awaiting_edition(
    asyncpg_pool: asyncpg.Pool,
    create_test_category,
    create_test_edition,
    create_test_child_cycle,
    create_test_map,
    n: int = 1,
) -> tuple[int, list[tuple[int, int, int]]]:
    """Create an awaiting_results edition with n finalizing child cycles."""
    edition_id, children = await _make_edition_with_cycles(
        asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=n
    )
    await _set_cycles_status(asyncpg_pool, edition_id, "finalizing")
    await _set_edition_status(asyncpg_pool, edition_id, "awaiting_results")
    return edition_id, children


class TestPollerFirstTickNoPending:
    """First tick, no in-flight verifications -> combined rollover, grants, completed (D-01/D-07)."""

    async def test_first_tick_no_pending_emits_combined(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """Zero pending: one combined TournamentRolloverEvent (results_pending=False), edition->completed, grants run."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="verified")
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        awarded: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            awarded.append(event.cycle_id)
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert isinstance(evt, TournamentRolloverEvent)
        assert evt.results_pending is False
        assert {e.cycle_id for e in evt.results} == {cycle_a}
        assert awarded == [cycle_a]  # grants ran for the child cycle
        # edition + cycles flipped to completed
        assert (await _edition_row(asyncpg_pool, edition_id))["status"] == "completed"
        assert await _cycle_statuses(asyncpg_pool, edition_id) == ["completed"]


class TestPollerFirstTickPending:
    """First tick, pending > 0 -> start-only rollover, results_pending=True, stays awaiting (D-05/D-07)."""

    async def test_first_tick_pending_emits_start_only(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """Pending exists: results_pending=True, results empty, start_announced set, no grants, stays awaiting_results."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="pending")
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        awarded: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            awarded.append(event.cycle_id)
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert isinstance(evt, TournamentRolloverEvent)
        assert evt.results_pending is True
        assert evt.results == []  # held: empty results -> bot skips transfer (D-05)
        assert awarded == []  # NO grants while pending
        ed = await _edition_row(asyncpg_pool, edition_id)
        assert ed["status"] == "awaiting_results"  # stays
        assert ed["start_announced"] is True
        # no edition_results row yet
        assert await _results_rows(asyncpg_pool, edition_id) == []


class TestPollerLaterTickDrained:
    """Later tick, start_announced, pending now 0 -> edition_results row, grants, completed (D-02/D-07)."""

    async def test_later_tick_drained_emits_results(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """After start_announced and drain: an edition_results outbox row is written, drained, grants run, completed."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        # Simulate: start already announced (first tick was pending), queue now drained (all verified).
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE tournaments.editions SET start_announced = TRUE WHERE id = $1", edition_id
            )
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="verified")
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        awarded: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            awarded.append(event.cycle_id)
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        # Tick 1: detects drain, writes an edition_results outbox row, flips completed.
        # The grant loop runs when the SAME poll loop drains the row (next tick),
        # exactly like an edition_rollover row -- so no grant on tick 1.
        await publish_pending_transitions(state)
        rows = await _results_rows(asyncpg_pool, edition_id)
        assert len(rows) == 1
        assert (await _edition_row(asyncpg_pool, edition_id))["status"] == "completed"
        assert await _cycle_statuses(asyncpg_pool, edition_id) == ["completed"]

        # Tick 2: the SAME loop drains the edition_results row, runs the grant loop,
        # and publishes it on the results key.
        await publish_pending_transitions(state)
        key = f"tournament:results:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert isinstance(evt, TournamentEditionResultsEvent)
        assert {e.cycle_id for e in evt.results} == {cycle_a}
        assert awarded == [cycle_a]  # grant ran exactly once, when the row drained


class TestPollerRerunNoDuplicateGrants:
    """Re-running the poller after completion does not double-grant or re-flip (idempotent)."""

    async def test_poller_rerun_no_duplicate_grants(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """A second poll finds no awaiting_results edition -> award_cycle_placements is not called again."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="verified")
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        awarded: list[int] = []

        async def _fake_award(self, event, *, conn):  # noqa: ANN001
            awarded.append(event.cycle_id)
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _fake_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)
        assert awarded == [cycle_a]
        assert (await _edition_row(asyncpg_pool, edition_id))["status"] == "completed"

        # Second poll: edition is no longer awaiting_results -> no second grant.
        await publish_pending_transitions(state)
        assert awarded == [cycle_a]  # unchanged


class TestPollerStackedEditions:
    """Two awaiting_results editions each publish independently when their queue drains."""

    async def test_stacked_editions_independent(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """One drained edition completes; a still-pending sibling stays awaiting_results."""
        # Drained edition.
        ed_drained, ch_d = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_d, map_d, cycle_d) = ch_d[0]
        u1 = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_d, u1, map_d, status="verified")

        # Still-pending edition.
        ed_pending, ch_p = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_p, map_p, cycle_p) = ch_p[0]
        u2 = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_p, u2, map_p, status="pending")

        # Clear unrelated unpublished rows (keep both our editions' rows).
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM tournaments.pending_transitions
                WHERE published = FALSE AND edition_id IS DISTINCT FROM $1 AND edition_id IS DISTINCT FROM $2
                """,
                ed_drained,
                ed_pending,
            )

        _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        # Drained edition completed; pending edition still awaiting_results (start_announced set).
        assert (await _edition_row(asyncpg_pool, ed_drained))["status"] == "completed"
        pending_ed = await _edition_row(asyncpg_pool, ed_pending)
        assert pending_ed["status"] == "awaiting_results"
        assert pending_ed["start_announced"] is True


class TestPollerEmptyEdition:
    """An edition whose cycles have empty leaderboards publishes a no-winner results event (Pitfall 6)."""

    async def test_empty_edition_no_winner(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
    ):
        """No submissions: combined rollover with empty standings and winner_user_id=None; edition->completed."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, _map_a, cycle_a) = children[0]
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert evt.results_pending is False
        assert len(evt.results) == 1
        assert evt.results[0].standings == []
        assert evt.results[0].winner_user_id is None
        assert (await _edition_row(asyncpg_pool, edition_id))["status"] == "completed"


# =============================================================================
# Quick task 260602-d96: boundary rollover carries the NEW edition's cycles
# =============================================================================
#
# Bug #1: the poller emitted boundary rollover events with started=[] in both
# branches, so the new tournament's cycle info never rode the boundary card.
# fetch_active_edition_started_cycles now sources the started list from the
# distinct status='active' edition the cron created at the boundary. These tests
# assert started is populated in both poller branches, and empty (no crash) when
# no active edition exists (paused/hiatus).


async def _retire_other_active_editions(pool: asyncpg.Pool) -> None:
    """Complete any pre-existing status='active' editions from sibling tests.

    fetch_active_edition_started_cycles is a GLOBAL query (no edition filter), so
    the session-shared DB may leak active editions/cycles from other tests into
    the started list (MEMORY: shared test-DB cross-test contamination). Retiring
    them first makes the started count deterministic for this test's own seed.
    """
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tournaments.editions SET status = 'completed' WHERE status = 'active'")


async def _seed_next_active_edition(
    asyncpg_pool: asyncpg.Pool,
    create_test_category,
    create_test_edition,
    create_test_child_cycle,
    create_test_map,
    n: int = 1,
) -> tuple[int, list[tuple[int, int, int]]]:
    """Create the 'next' status='active' edition with n active child cycles.

    This mirrors what migration 0025 process_edition_transitions does at a
    boundary: alongside flipping the due edition to awaiting_results, it creates
    the NEXT edition with status='active' and active child cycles. The poller's
    fetch_active_edition_started_cycles reads exactly this edition. Pre-existing
    active editions are retired first so the started count is deterministic.
    """
    await _retire_other_active_editions(asyncpg_pool)
    return await _make_edition_with_cycles(
        asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=n
    )


class TestPollerStartedPopulatedCombined:
    """Bug #1: combined branch publishes a rollover with started populated from the active edition."""

    async def test_combined_branch_started_populated(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """No pending -> combined rollover with results populated AND started from the next active edition."""
        # The due edition (awaiting_results, one finalizing child cycle + a verified completion).
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="verified")

        # The NEXT active edition the cron created at the boundary (2 active child cycles).
        next_ed, next_children = await _seed_next_active_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=2
        )
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert isinstance(evt, TournamentRolloverEvent)
        assert evt.results_pending is False
        # results populated (the due edition's finalizing cycle).
        assert {e.cycle_id for e in evt.results} == {cycle_a}
        # started populated from the NEXT active edition's active child cycles.
        assert len(evt.started) == 2
        started_cycle_ids = {s.cycle_id for s in evt.started}
        assert started_cycle_ids == {c[2] for c in next_children}
        for s in evt.started:
            assert s.map_code  # joined from core.maps
            assert s.map_name
            assert s.started_at is not None
            assert s.ends_at is not None


class TestPollerStartedPopulatedStartOnly:
    """Bug #1: start-only branch (pending > 0) also publishes started populated, results empty."""

    async def test_start_only_branch_started_populated(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """Pending exists -> start-only rollover with results=[] AND started populated AND results_pending=True."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="pending")

        next_ed, next_children = await _seed_next_active_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert isinstance(evt, TournamentRolloverEvent)
        assert evt.results_pending is True
        assert evt.results == []  # held
        assert len(evt.started) == 1
        assert {s.cycle_id for s in evt.started} == {c[2] for c in next_children}


class TestPollerStartedEmptyWhenPaused:
    """Bug #1 edge: no active edition (paused/hiatus) -> started=[], ended-only card, no crash."""

    async def test_no_active_edition_started_empty(
        self,
        asyncpg_pool: asyncpg.Pool,
        monkeypatch: pytest.MonkeyPatch,
        create_test_category,
        create_test_edition,
        create_test_child_cycle,
        create_test_map,
        create_test_user,
    ):
        """With NO status='active' edition, the combined rollover carries started=[] and still publishes."""
        edition_id, children = await _make_awaiting_edition(
            asyncpg_pool, create_test_category, create_test_edition, create_test_child_cycle, create_test_map, n=1
        )
        (cat_a, map_a, cycle_a) = children[0]
        user_id = await create_test_user()
        await _seed_completion(asyncpg_pool, cycle_a, user_id, map_a, status="verified")

        # Paused/hiatus: ensure NO status='active' edition exists anywhere (complete any
        # leftover active editions from sibling tests so fetch_active_edition_started_cycles
        # returns []).
        async with asyncpg_pool.acquire() as conn:
            await conn.execute("UPDATE tournaments.editions SET status = 'completed' WHERE status = 'active'")
        await _clear_other_unpublished(asyncpg_pool, edition_id)

        calls = _stub_publish(monkeypatch)
        import services.tournament_reward_service as reward_module

        async def _noop_award(self, event, *, conn):  # noqa: ANN001
            return []

        monkeypatch.setattr(reward_module.TournamentRewardService, "award_cycle_placements", _noop_award)
        state = State({"db_pool": asyncpg_pool})

        # Must NOT raise.
        await publish_pending_transitions(state)

        key = f"tournament:rollover:{edition_id}"
        our = [c for c in calls if c["idempotency_key"] == key]
        assert len(our) == 1
        evt = our[0]["data"]
        assert isinstance(evt, TournamentRolloverEvent)
        assert evt.started == []  # ended-only card
        assert {e.cycle_id for e in evt.results} == {cycle_a}
        assert (await _edition_row(asyncpg_pool, edition_id))["status"] == "completed"


class TestWinnerDedupeTransform:
    """Bug #2: the order-preserving dedupe the bot handlers apply before AllowedMentions."""

    def test_dict_fromkeys_dedupes_order_preserving(self):
        """list(dict.fromkeys(...)) drops duplicates while preserving first-seen order.

        This is the exact transform both _on_edition_rollover and _on_edition_results now
        use to dedupe winner ids before discord.AllowedMentions(users=...). A user winning
        multiple categories would otherwise appear twice and trigger Discord's 400 50035
        'set already contains this value' DLQ crash. There is no bot pytest harness, so this
        guards the pure transform directly.
        """
        winners = [111, 222, 111, 333, 222]
        deduped = list(dict.fromkeys(winners))
        # duplicate-free
        assert len(deduped) == len(set(deduped))
        # order-preserving (first occurrence wins)
        assert deduped == [111, 222, 333]
        # idempotent on an already-unique list
        assert list(dict.fromkeys(deduped)) == deduped
