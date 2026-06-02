# Phase 8: Rewards Engine - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 9 (3 NEW, 5 MODIFIED, 1 optional SDK edit)
**Analogs found:** 9 / 9 (every file has an in-repo analog — pure brownfield phase)

> All XP delivery routes through the EXISTING grant mechanism (`lootbox.xp` upsert +
> generic `XpGrantEvent` → `api.xp.grant`). Do NOT publish `TournamentXpGrantEvent`
> (zero consumers; the bot consumer at `apps/bot/extensions/xp.py:106` decodes
> `XpGrantEvent` and dereferences `type`/`previous_amount`/`new_amount`, which the
> tournament struct lacks). This is the load-bearing contract for the whole phase.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/migrations/0022_tournament_xp_grants.sql` (NEW) | migration | CRUD (ledger) | `apps/api/migrations/0020_tournaments.sql` | role-match (additive table, same schema) |
| `apps/api/services/tournament_reward_service.py` (NEW) | service | event-driven + transform | `apps/api/services/lootbox_service.py` (grant), `tournament_outbox_service.py` (cycle-end flow) | exact (XP grant + publish) |
| `apps/api/repository/tournaments_repository.py` (MODIFIED) | repository | CRUD | same file: `upsert_streak`, `fetch_user_completion`, `fetch_category` | exact (same file, same conventions) |
| `apps/api/services/tournament_service.py` (MODIFIED) | service | request-response | same file: `submit_completion` txn block (line 491-531) | exact (in-place hook) |
| `apps/api/services/tournament_outbox_service.py` (MODIFIED) | service | event-driven | same file: `publish_pending_transitions` (line 71-105) | exact (in-place hook) |
| `apps/api/services/lootbox_service.py` (MODIFIED) | service | CRUD + pub | same file: `grant_user_xp` (line 373-417) — extract `conn`-accepting helper | exact |
| `libs/sdk/src/genjishimada_sdk/xp.py` (MODIFIED, optional) | model | n/a | same file: `XP_TYPES` literal (line 17) | exact (one-line literal add) |
| `apps/api/services/exceptions/tournaments.py` (MODIFIED, if needed) | exception | n/a | same file: `TournamentsError` subclasses | exact |
| `apps/api/tests/services/test_tournament_reward_service.py` + `tests/integration/test_tournament_rewards.py` (NEW) | test | n/a | `tests/services/test_tournament_service.py`, `tests/services/test_lootbox_service.py:441`, `tests/integration/test_tournaments_integration.py` | exact |

---

## Pattern Assignments

### `apps/api/migrations/0022_tournament_xp_grants.sql` (NEW — migration, CRUD ledger)

**Analog:** `apps/api/migrations/0020_tournaments.sql`

**Migration header + BEGIN/COMMIT + schema-qualified table pattern** (`0020` lines 1-22, 31-45):
```sql
-- Migration: Add tournaments schema
-- Description: ...
-- Date: 2026-05-29

BEGIN;

CREATE TABLE IF NOT EXISTS tournaments.categories
(
    id               int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ...
);

COMMENT ON TABLE tournaments.categories IS '...';
```

**What to copy / build for 0022** (shape from RESEARCH.md Q4, follows `0020` conventions):
- `BEGIN; ... COMMIT;` wrapper (every tournaments migration uses it).
- `id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY` (matches every `0020` table).
- `user_id bigint NOT NULL REFERENCES core.users(id) ON DELETE CASCADE` — **`bigint`** because `core.users.id` is a Discord snowflake; `0021` explicitly widened `v_winner` to `bigint` (line 104). Do NOT use `int`.
- `cycle_id int NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE`.
- `reason text NOT NULL CHECK (reason IN ('participation', 'placement', 'streak'))` — mirrors the `CHECK (... IN (...))` style used on `categories.cycle_frequency` (`0020` line 37) and `config.id` (line 18).
- `UNIQUE (cycle_id, user_id, reason)` — **the at-least-once guard**.
- `granted_at timestamptz NOT NULL DEFAULT now()` (matches `created_at`/`updated_at` convention).
- `CREATE INDEX IF NOT EXISTS idx_xp_grants_cycle ...` / `idx_xp_grants_user ...`.
- `COMMENT ON TABLE/COLUMN` lines (every `0020` table is commented).

**Test fixture note:** `apps/api/tests/conftest.py:58-74` (`_apply_sql_dir`) globs `migrations/*.sql` sorted, so `0022` is auto-applied to the test DB. No fixture change needed.

---

### `apps/api/services/tournament_reward_service.py` (NEW — service, event-driven + transform)

**Analog (XP grant + publish):** `apps/api/services/lootbox_service.py:373-417` (`grant_user_xp`)
**Analog (service skeleton + DI):** `apps/api/services/tournament_service.py:45-62, 576-590`
**Analog (cycle-end flow it hooks into):** `apps/api/services/tournament_outbox_service.py:71-105`

**Service class + `__init__` + super pattern** (from `tournament_service.py:45-62`):
```python
class TournamentService(BaseService):
    def __init__(self, pool: Pool, state: State, tournament_repo: TournamentRepository) -> None:
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo
```
New service extends `BaseService`, takes `pool, state, tournament_repo` (and optionally `lootbox_repo` to reach `upsert_user_xp`/`fetch_xp_multiplier`).

**DI provider pattern** (from `tournament_service.py:576-590`):
```python
async def provide_tournament_service(state: State, tournament_repo: TournamentRepository) -> TournamentService:
    return TournamentService(state.db_pool, state, tournament_repo)
```

**Canonical XP-grant-and-publish (the contract to reuse — DO copy this shape)** (`lootbox_service.py:389-415`):
```python
multiplier = await self._lootbox_repo.fetch_xp_multiplier()           # add conn=conn (see Q4)
result = await self._lootbox_repo.upsert_user_xp(
    user_id=user_id, xp_amount=data.amount, multiplier=float(multiplier),
)                                                                      # add conn=conn
event = XpGrantEvent(
    user_id=user_id,
    amount=data.amount,
    type=data.type,                     # "Other" or new "Tournament" XP_TYPES member
    previous_amount=result["previous_amount"],
    new_amount=result["new_amount"],
    reason=data.reason,                 # e.g. "Tournament Participation", "Tournament Placement #1"
)
await self.publish_message(routing_key="api.xp.grant", data=event, headers=headers)
```

**Publish path constraints** (`base.py:56-113`):
- `publish_message` is `kw_only` (`*, routing_key, data, headers, idempotency_key=None`).
- `api.xp.grant ∈ IGNORE_IDEMPOTENCY` (`base.py:34`) → `idempotency_key` is OPTIONAL; pass `tournament:{reason}:{cycle_id}:{user_id}` as a best-effort second line of defense (the DB ledger is the real guard).
- `X-PYTEST-ENABLED == "1"` header short-circuits publish (returns success without touching the broker) — `base.py:80`. This is the test seam.
- Publish failures degrade gracefully (return `failed` JobStatus, do NOT raise) — `base.py:111-113`. Treat publish as after-commit notification.

**Placement mapping (Python transform, reading the event)** — from RESEARCH.md Q5 + `tournaments.py:282-299, 425-438`:
```python
placement_by_place = {tier.place: tier.xp for tier in category.placement_xp}   # PlacementXpTier
for entry in event.standings:                       # TournamentLeaderboardEntryResponse (.rank, .user_id)
    xp = placement_by_place.get(entry.rank)         # None -> beyond configured tiers, skip
    if not xp:
        continue
    if await repo.claim_xp_grant(event.cycle_id, entry.user_id, "placement", xp, conn=conn):
        await self._grant_xp(entry.user_id, xp, reason=f"Tournament Placement #{entry.rank}", conn=conn)
```
Decode the outbox payload via `msgspec.convert(payload, TournamentCycleCompletedEvent)` (the outbox already does this in `_build_event`, `tournament_outbox_service.py:66-68`) — read typed fields, never raw dict keys (Pitfall 5).

---

### `apps/api/repository/tournaments_repository.py` (MODIFIED — repository, CRUD)

**Analog:** same file — `upsert_streak` (699-738), `fetch_user_completion` (914-941), `fetch_category` (148-166), `create_pending_transition` (947-984).

**Imports already present** (lines 1-21): `Connection, Pool` from asyncpg; `CheckViolationError, ForeignKeyViolationError, UniqueViolationError`; repo exceptions `CheckConstraintViolationError, UniqueConstraintViolationError, extract_constraint_name`, `ForeignKeyViolationError as RepoFKError`; `log = getLogger(__name__)`. Reuse — no new imports beyond what's there.

**Method signature + `_get_connection` + positional `$N` + dict-conversion pattern** (from `fetch_category` 148-166):
```python
async def fetch_category(self, category_id: int, *, conn: Connection | None = None) -> dict | None:
    _conn = self._get_connection(conn)
    query = "SELECT * FROM tournaments.categories WHERE id = $1"
    row = await _conn.fetchrow(query, category_id)
    return dict(row) if row else None
```

**Existing increment-only `upsert_streak` (DO NOT reuse for cycle-end — it has no reset path)** (699-738):
```python
query = """
    INSERT INTO tournaments.streaks (user_id, current_streak, max_streak, last_cycle_id, updated_at)
    VALUES ($1, 1, 1, $2, now())
    ON CONFLICT (user_id) DO UPDATE SET
        current_streak = tournaments.streaks.current_streak + 1,
        max_streak = GREATEST(tournaments.streaks.max_streak, tournaments.streaks.current_streak + 1),
        last_cycle_id = $2,
        updated_at = now()
    RETURNING user_id, current_streak, max_streak, last_cycle_id, updated_at
"""
```
**New methods to ADD (copy the conventions above):**
- `claim_xp_grant(cycle_id, user_id, reason, amount, *, conn=None) -> bool` — `INSERT INTO tournaments.xp_grants (...) ON CONFLICT (cycle_id, user_id, reason) DO NOTHING RETURNING id`; return `row is not None` (RESEARCH.md "Ledger-guarded grant").
- A **reset-capable** streak update keyed on participation (increment participants, reset non-participants to 0, set `last_cycle_id`). Guard the increment against double-counting via `last_cycle_id` (Pitfall 1). Use the existing `INSERT ... ON CONFLICT ... DO UPDATE` style; a CTE is acceptable per CONVENTIONS for multi-row atomic writes.
- A per-cycle participant query off `tournaments.completions` (mirror `fetch_user_completion`'s `WHERE cycle_id = $1` style; `SELECT DISTINCT user_id`).
- `fetch_category(...)` already exists (148) — reuse to read `participation_xp` / `placement_xp` / `streak_xp`.

**FK error translation pattern** (from `upsert_streak` 736-738) — apply to ledger insert if FK violations need user-facing translation:
```python
except ForeignKeyViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise RepoFKError(constraint_name, "tournaments.streaks", str(e)) from e
```

---

### `apps/api/services/tournament_service.py` (MODIFIED — participation XP hook)

**Analog / hook point:** same file, `submit_completion` (468-531). The open transaction is at line 491; the first-completion signal is the `existing is None` branch.

**Existing transaction + first-completion check** (491-531):
```python
async with self._pool.acquire() as conn, conn.transaction():
    cycle = await self._tournament_repo.fetch_cycle(cycle_id, conn=conn)
    ...
    existing = await self._tournament_repo.fetch_user_completion(cycle_id, data.user_id, conn=conn)
    if existing is not None and data.time >= existing["time"]:
        raise SlowerTimeError(...)
    row = await self._tournament_repo.create_tournament_completion(...)
    await self._tournament_repo.cross_write_to_core(...)
    log.info("[->] Tournament completion submitted for cycle %s by user %s", cycle_id, data.user_id)
```
**Hook placement:** award participation XP only when `existing is None` (first ever completion this cycle — the check runs BEFORE the insert, so `None` is the correct signal, Pitfall 3). Call the reward service's `award_participation(..., conn=conn)` **inside this transaction** so the ledger insert + `lootbox.xp` upsert are atomic with the completion. This requires the `conn`-accepting helper (see lootbox edit). `cycle["category_id"]` is available from the fetched cycle to read `participation_xp`.

**Logging convention** (line 529): `%s`-style, `[->]` publish marker — match it for reward log lines (`[→]/[✓]/[x]/[!]`).

---

### `apps/api/services/tournament_outbox_service.py` (MODIFIED — placement + streak hook)

**Analog / hook point:** same file, `publish_pending_transitions` (71-105). Recommended Option A (RESEARCH.md): run cycle-end rewards inside this outbox transaction when `event_type == 'cycle_completed'`.

**Existing outbox txn + per-row publish loop** (93-104):
```python
async with pool.acquire() as conn, conn.transaction():
    rows = await repository.fetch_unpublished_transitions(conn=conn)
    for row in rows:
        routing_key, event = _build_event(row)            # event is the typed SDK struct
        await service.publish_message(
            routing_key=routing_key, data=event, headers=Headers({}),
            idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}",
        )
        await repository.mark_transition_published(row["id"], conn=conn)
```
**Hook placement:** after `_build_event` yields a `cycle_completed` `TournamentCycleCompletedEvent`, call `reward_service.award_cycle_end(event, conn=conn)` inside the SAME `conn`/transaction (before or after `mark_transition_published`). Replay-safe via the `0022` ledger's `ON CONFLICT DO NOTHING`. The reward's own `api.xp.grant` publishes are separate messages within the same poll.

**Poller cadence (no new scheduler):** `app.py:72-94` runs `publish_pending_transitions` on a ~10s loop with a broad `except`; rewards ride on this — do NOT add a second poller.

---

### `apps/api/services/lootbox_service.py` (MODIFIED — extract `conn`-accepting grant helper)

**Analog:** same file, `grant_user_xp` (373-417). **Critical gap:** it does NOT accept `conn` and acquires its own pool connection via `upsert_user_xp`/`fetch_xp_multiplier`, so calling it from inside the submit/outbox transaction breaks atomicity (RESEARCH.md Q4 caveat, Pitfall 2).

**Current signature (does not enlist in caller txn):**
```python
async def grant_user_xp(self, headers: Headers, user_id: int, data: XpGrantRequest) -> XpGrantResponse:
    multiplier = await self._lootbox_repo.fetch_xp_multiplier()        # own connection
    result = await self._lootbox_repo.upsert_user_xp(user_id=user_id, xp_amount=data.amount, multiplier=float(multiplier))
    ...
```
**What to extract:** a `conn`-accepting helper, e.g. `grant_xp(user_id, amount, type, reason, headers, *, conn=None) -> XpGrantResponse` that threads `conn=conn` into `fetch_xp_multiplier(conn=conn)` and `upsert_user_xp(..., conn=conn)` (both repo methods already accept `conn` — see `lootbox_repository.py:539-558`), then publishes `XpGrantEvent`. `grant_user_xp` can delegate to it for backward compatibility. The reward service calls this helper inside the open transaction. Keep the RabbitMQ publish best-effort/after-commit.

**`upsert_user_xp` already accepts conn** (`lootbox_repository.py:539-558`) and returns `{previous_amount, new_amount}` — the helper passes `conn` straight through.

---

### `libs/sdk/src/genjishimada_sdk/xp.py` (MODIFIED, optional — add `"Tournament"` to `XP_TYPES`)

**Analog:** same file, line 17. One-line literal edit:
```python
XP_TYPES = Literal["Map Submission", "Playtest", "Guide", "Completion", "Record", "World Record", "Quest", "Other", "Tournament"]
```
- Do NOT add a `XP_AMOUNTS` entry (tournament amounts are config-driven, not table-driven).
- If edited, run `just fix` to reinstall the workspace SDK so API/bot see the new literal BEFORE running tests (MEMORY.md SDK-import note).
- Acceptable alternative: keep `type="Other"` + descriptive `reason`. Either works for the consumer; `"Tournament"` only helps XP-source analytics. Flag as a discretion decision for the planner.

---

### `apps/api/services/exceptions/tournaments.py` (MODIFIED, only if needed)

**Analog:** same file. New reward errors (if any) extend `TournamentsError(DomainError)` (line 10) and follow the `super().__init__("message", **context)` pattern:
```python
class CategoryNotFoundError(TournamentsError):
    def __init__(self, category_id: int) -> None:
        super().__init__("Tournament category not found.", category_id=category_id)
```
Most reward paths are no-ops on missing config (skip), so new exceptions may be unnecessary — add only if a hard failure needs HTTP translation. Avoid the deprecated `handle_db_exceptions` decorator (CLAUDE.md).

---

### Tests (NEW)

**Unit analog:** `apps/api/tests/services/test_tournament_service.py` (mock fixtures + dict factories) and `tests/services/test_lootbox_service.py:441-482` (publish-seam pattern).

**Service test fixtures** (`tests/services/conftest.py`): `mock_pool` (39), `mock_state` (76), `mock_tournament_repo` (216, `AsyncMock(spec=TournamentRepository)`), `mock_lootbox_repo` (147). Add a `mock_*_reward_repo` only if a separate repo is introduced; otherwise reuse `mock_tournament_repo`.

**Publish-seam assertion pattern** (`test_lootbox_service.py:453-461`):
```python
mock_publish = mocker.patch.object(service, "publish_message", new_callable=AsyncMock)
await service.grant_user_xp(headers={}, user_id=123, data=data)
mock_publish.assert_called_once()
event = mock_publish.call_args.kwargs["data"]
assert isinstance(event, XpGrantEvent)
assert event.reason == "..."
```
Use this to assert the correct `XpGrantEvent` payloads (user_id, amount, type, reason) for participation/placement/streak without a broker.

**Dict-factory pattern for mock repo returns** (`test_tournament_service.py:25-72`): build `_category(participation_xp=50, placement_xp=[...], streak_xp=[...])`, `_cycle(category_id=1)`, `_leaderboard_entry(rank=1, user_id=100)` lambdas.

**Integration analog:** `tests/integration/test_tournaments_integration.py` (real DB, `test_client`, `pytestmark = [pytest.mark.integration, pytest.mark.domain_tournaments]`). Integration tests assert on real `tournaments.xp_grants` + `tournaments.streaks` + `lootbox.xp` rows. Migrations (incl. `0022`) auto-applied by `tests/conftest.py:58-74` glob.

**Test commands** (MEMORY.md): `uv run --directory apps/api pytest tests/services/test_tournament_reward_service.py -p no:xdist`; full `just test-api`.

---

## Shared Patterns

### XP Grant Delivery (THE contract — applies to all three reward reasons)
**Source:** `apps/api/services/lootbox_service.py:389-415`
**Consumer (do not break):** `apps/bot/extensions/xp.py:106` (`@queue_consumer("api.xp.grant", struct_type=XpGrantEvent, idempotent=True)`)
**Apply to:** every reward grant in `TournamentRewardService`.
- Mutate `lootbox.xp` via `upsert_user_xp` (returns `previous_amount`/`new_amount`) FIRST, then build + publish `XpGrantEvent` with those amounts. The event is a post-write notification, not a request.
- `type` ∈ existing `XP_TYPES` (`"Other"` or new `"Tournament"`); `reason` carries the specifics.

### Double-Grant Guard (at-least-once safety)
**Source:** RESEARCH.md "Ledger-guarded grant" + `0022` `UNIQUE(cycle_id, user_id, reason)`
**Apply to:** participation, placement, AND streak grants.
- `claim_xp_grant(...) -> bool` via `INSERT ... ON CONFLICT DO NOTHING RETURNING id`; only grant XP if `True`.
- Run the ledger insert + `lootbox.xp` upsert in the SAME transaction (the caller's `conn`).
- `api.xp.grant` is non-idempotent (`base.py:34`) — the DB ledger is the only real guard; `idempotency_key` is best-effort.

### Repository Conventions
**Source:** `apps/api/repository/tournaments_repository.py` (throughout)
**Apply to:** all new repo methods.
- `*, conn: Connection | None = None` keyword-only; `_conn = self._get_connection(conn)`.
- Positional `$N` params only (never f-string SQL); `dict(row) if row else None/{}`; CTEs for atomic multi-table writes.
- Translate asyncpg violations to repo exceptions with `extract_constraint_name(e)` + `from e`.

### Logging
**Source:** CLAUDE.md / `tournament_service.py:529`, `tournament_outbox_service.py:104`
**Apply to:** all new service code.
- `log = getLogger(__name__)`; `%s`-style (never f-strings); markers `[→]` publish, `[✓]` success, `[x]` failure, `[!]` error.

---

## No Analog Found

None. Every file has a direct in-repo analog (this is a wiring-existing-parts phase — the only genuinely new persistent state is the `0022` grants ledger, and even that follows the `0020` table conventions).

## Metadata

**Analog search scope:** `apps/api/services/`, `apps/api/repository/`, `apps/api/migrations/`, `apps/api/tests/{services,integration}/`, `libs/sdk/src/genjishimada_sdk/`, `apps/bot/extensions/`
**Files scanned:** ~16 (lootbox_service, base, tournament_service, tournament_outbox_service, tournaments_repository, lootbox_repository, xp.py, tournaments.py, exceptions/tournaments.py, 0020/0021 migrations, 4 test files + conftests, app.py)
**Pattern extraction date:** 2026-05-30
