# Phase 14: Skill Score Dashboard - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 9 (1 migration, 1 repo, 1 service, 1 route controller, 2 event files, 1 completions service, 1 SDK module, 2 test files)
**Analogs found:** 9 / 9 (all in-repo, same domain — this is a Phase 13 extension, not greenfield)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/migrations/0031_skill_history.sql` (new) | migration | DDL / batch | `apps/api/migrations/0027_skill_score.sql` | exact (same schema) |
| `apps/api/repository/skill_repository.py` (modify) | repository | CRUD + bulk-insert | self — `replace_snapshot`, `fetch_snapshot`, `fetch_weights` | exact |
| `apps/api/services/skill_service.py` (modify) | service | transform + capture | self — `recompute_all` / `_do_recompute` / `_player_breakdown` / `update_tier_config` | exact |
| `apps/api/routes/v3/skill.py` (modify) | route / controller | request-response (GET reads) | self — existing `/skill/*` GET routes + `tournaments.py:817` pagination | exact + role-match |
| `apps/api/events/schemas.py` (modify) | model (event struct) | event-driven | self — `SkillRecomputeRequestedEvent` | exact |
| `apps/api/events/skill.py` (modify) | listener | event-driven | self — `handle_skill_recompute` | exact |
| `apps/api/services/completions_service.py` (modify) | service | event-driven (emit) | self — `_emit_skill_recompute` + 5 call sites | exact |
| `libs/sdk/src/genjishimada_sdk/skill.py` (modify) | model (msgspec structs) | transform | self — `SkillSummaryResponse`, `SkillBreakdownRow`, `Weights` | exact |
| `apps/api/tests/integration/test_skill_dashboard.py` (new) | test | n/a | `apps/api/tests/integration/test_skill.py` (`seed`, `_recompute`) | exact |
| `apps/api/tests/services/test_skill_service.py` (extend) | test | n/a | self — `_make_service`, `_reset_guard`, mocked-repo asserts | exact |

**Note:** Every analog is the same-domain Phase 13 file. This phase copies its own predecessor's patterns — the strongest possible match quality. There is no "No Analog Found" section.

## Pattern Assignments

### `apps/api/migrations/0031_skill_history.sql` (migration, DDL)

**Analog:** `apps/api/migrations/0027_skill_score.sql` (read in full, 55 lines)

**Header + transaction + schema-guard pattern** (`0027_skill_score.sql:1-12`):
```sql
-- Migration: Add skill schema + snapshot + weight config
-- Description: ...
-- Date: 2026-06-12

BEGIN;

CREATE SCHEMA IF NOT EXISTS skill;
```

**Table DDL idiom — `CREATE TABLE IF NOT EXISTS`, type idioms, inline CHECK, jsonb default** (`0027_skill_score.sql:16-43`):
```sql
CREATE TABLE IF NOT EXISTS skill.snapshot
(
    user_id      bigint PRIMARY KEY,
    skill_score  double precision NOT NULL,
    breakdown    jsonb            NOT NULL DEFAULT '[]'::jsonb,  -- jsonb<->msgspec codec
    computed_at  timestamptz      NOT NULL DEFAULT now()
);
-- gamma >= 0.5 enforced at schema level:
CONSTRAINT weight_config_gamma_floor CHECK (gamma >= 0.5)
```
File closes with `COMMIT;` (`0027:54`).

**Adaptation needed (D-01, RESEARCH §Migration Conventions):**
- Two new tables in `skill` schema:
  - `skill.score_history` — `(user_id bigint, captured_at timestamptz, skill_score double precision)`, PK `(user_id, captured_at)`. This composite PK covers all `/history` window reads — no extra index needed.
  - `skill.score_change` — `change_id bigserial PRIMARY KEY, user_id bigint NOT NULL, captured_at timestamptz NOT NULL, previous_score double precision NOT NULL, new_score double precision NOT NULL, delta double precision NOT NULL, cause_category text NOT NULL, reason text, diff jsonb NOT NULL DEFAULT '{}'::jsonb`.
- `cause_category` is **text + CHECK, never a Postgres enum** (RESEARCH:212 — no `CREATE TYPE` exists in skill migrations): `CHECK (cause_category IN ('PLAYER_ACTION','MAP_ENVIRONMENT','SYSTEM'))`, paired with an msgspec `Literal` in the SDK.
- Add explicit feed index: `CREATE INDEX IF NOT EXISTS skill_score_change_user_captured_idx ON skill.score_change (user_id, captured_at DESC);` (the existing skill tables declare no indexes beyond PKs, so this is a net-new but conventional addition).
- `bigserial` for `change_id` is house-acceptable (0027/0028 use `integer GENERATED ALWAYS AS IDENTITY`; both idiomatic — `bigserial` fits unbounded forward-only growth, A5).
- Migration auto-applies on the fresh test DB via `conftest.py:_apply_sql_dir` (RESEARCH:215) — being valid SQL satisfies the "applies cleanly" acceptance criterion. **No backfill INSERT** (forward-only, SPEC).

---

### `apps/api/repository/skill_repository.py` (repository, CRUD + bulk-insert)

**Analog:** self — `replace_snapshot` (lines 185-229), `fetch_snapshot` (168-183), `fetch_weights` (231-249), `fetch_skill_inputs` (132-149)

**`*, conn` convention + `_get_connection`** (every method, e.g. `168-183`):
```python
async def fetch_snapshot(self, user_id: int, *, conn: Connection | None = None) -> dict | None:
    _conn = self._get_connection(conn)
    row = await _conn.fetchrow("SELECT * FROM skill.snapshot WHERE user_id = $1", user_id)
    return dict(row) if row else None
```
**ALL new repo methods MUST take `*, conn: Connection | None = None` and call `self._get_connection(conn)`** (RESEARCH:159).

**Bulk-insert house style — `executemany` + positional-tuple list comprehension, NOT COPY/unnest** (`replace_snapshot`, lines 199-222):
```python
async def _do_replace(c: Connection | PoolConnectionProxy) -> None:
    async with c.transaction():
        await c.execute("TRUNCATE skill.snapshot")
        if not rows:
            return
        await c.executemany(
            """
            INSERT INTO skill.snapshot
                (user_id, skill_score, maps_cleared, video_clears, hardest_raw, breakdown, computed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [(r["user_id"], r["skill_score"], r["maps_cleared"], r["video_clears"],
              r["hardest_raw"], r["breakdown"], r["computed_at"]) for r in rows],
        )
```
Note the Pool-vs-Connection fork at lines 224-229 (`if isinstance(_conn, Pool): async with _conn.acquire()`). **The two new bulk-insert methods mirror this exactly** — except they do NOT TRUNCATE (history is append-only/forward-only). `r["diff"]` is a Python dict; the jsonb codec (`app.py:207`) serializes it automatically, exactly like `breakdown`.

**Adaptation needed (RESEARCH §Repository Surface, "New methods needed"):**
- `fetch_all_snapshots(*, conn=None) -> dict[int, dict]` — bulk read of all `(user_id, skill_score, breakdown)` rows BEFORE `replace_snapshot` truncates (Pitfall 1/3). One query, returns `{user_id: {"skill_score", "breakdown"}}`; `breakdown` decodes via jsonb codec.
- `bulk_insert_history(rows, *, conn=None)` — `executemany` into `skill.score_history` (no TRUNCATE).
- `bulk_insert_changes(rows, *, conn=None)` — `executemany` into `skill.score_change`; `diff` is a Python dict (jsonb codec). Columns per the migration: `(user_id, captured_at, previous_score, new_score, delta, cause_category, reason, diff)`.
- `fetch_history(user_id, since, *, conn=None)` — `WHERE user_id=$1 AND captured_at >= $2 ORDER BY captured_at` (for `all` pass a sentinel epoch or build the WHERE conditionally).
- `fetch_changes(user_id, since, limit, offset, *, conn=None)` — `ORDER BY captured_at DESC LIMIT $.. OFFSET $..` over the `(user_id, captured_at DESC)` index.
- `fetch_change(user_id, change_id, *, conn=None) -> dict | None` — **ownership predicate** `WHERE change_id=$1 AND user_id=$2`; returns None → route raises 404 (IDOR mitigation, RESEARCH §Security V4).

---

### `apps/api/services/skill_service.py` (service, transform + capture)

**Analog:** self — `_RecomputeGuard` (47-67), `recompute_all` (178-199), `_do_recompute` (201-230), `_player_breakdown` (130-161), `update_tier_config` (307-339), read-method empty-rule (`get_user_skill` 232-257, `get_user_breakdown` 259-271)

**`_RecomputeGuard` module-scope accumulator (D-10 extension point)** (lines 55-67):
```python
class _RecomputeGuard:
    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self.rerun_requested = False
    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

_GUARD = _RecomputeGuard()   # module scope — one per process
```
**Adaptation (D-10):** add a `pending: list[TriggerDescriptor]` accumulator field (define a small `TriggerDescriptor` struct/dataclass carrying `cause_category` + `actor_user_id`). MUST stay module-scope (a fresh `SkillService` is built per request, RESEARCH:85).

**Burst-collapse loop — where the cause decision goes** (`recompute_all`, lines 192-199):
```python
_GUARD.rerun_requested = True
if _GUARD.lock.locked():
    return                                  # rebuild running; it picks up the flag
async with _GUARD.lock:
    while _GUARD.rerun_requested:
        _GUARD.rerun_requested = False
        await self._do_recompute()
```
**Adaptation (D-10, Pitfall 2):** `recompute_all(descriptor)` appends `descriptor` to `_GUARD.pending` **before** the `lock.locked()` early return. Then **inside the `while` loop, per iteration**, drain `_GUARD.pending` and resolve the cause policy: exactly 1 descriptor with `actor_user_id` → `(PLAYER_ACTION, actor)`; ≥2 pending OR any SYSTEM → `(SYSTEM, "global recalculation")`. Pass the policy into `_do_recompute(policy)`. **Drain INSIDE the loop, not before it** (Pitfall 2 — descriptors arriving mid-rebuild belong to the rerun).

**`_do_recompute` capture wiring site (D-05)** (lines 201-230):
```python
computed_at = datetime.now(timezone.utc)          # (a) line 210 — reuse as captured_at (D-02)
snapshot_rows: list[dict] = []
for user_id, urows in by_user.items():
    snapshot_rows.append({... "breakdown": _player_breakdown(urows, w), "computed_at": computed_at})
await self._skill_repo.replace_snapshot(snapshot_rows)   # (c) TRUNCATEs — prev GONE after this
await self._skill_repo.compute_tier_boundaries()
```
**Adaptation (D-05, RESEARCH §Recompute Control Flow):**
1. `prev = await self._skill_repo.fetch_all_snapshots(conn=conn)` **before** `replace_snapshot` (Pitfall 1 — must read prev score+breakdown before TRUNCATE).
2. Reuse the existing `computed_at` (line 210) as the single `captured_at` for all rows (D-02 — do NOT mint a second timestamp).
3. Per user, build `score_history` rows and `score_change` rows: `previous_score = prev.get(uid, {}).get("skill_score", 0.0)`; `diff.maps` = prev breakdown vs new breakdown joined on `map_name` (A2/Pitfall 4), `impact = new.contribution - prev.contribution`; a map only-before → `new=0`, only-after → `prev=0`.
4. Per-user `cause_category` from the resolved policy: actor → PLAYER_ACTION, all other users → MAP_ENVIRONMENT (D-08); or all SYSTEM (D-09).
5. Call `bulk_insert_history` + `bulk_insert_changes` after `replace_snapshot`.

**Atomic transaction (mirror `update_tier_config`, lines 335-338):**
```python
async with self._pool.acquire() as conn, conn.transaction():
    await self._skill_repo.update_percentiles(percentiles, conn=conn)
    await self._skill_repo.compute_tier_boundaries(conn=conn)
    row = await self._skill_repo.fetch_tier_config(conn=conn)
```
**Adaptation (Pitfall 6):** wrap `fetch_all_snapshots` + `replace_snapshot` + `bulk_insert_history` + `bulk_insert_changes` + `compute_tier_boundaries` in ONE `async with self._pool.acquire() as conn, conn.transaction():` passing `conn=conn` to all five — all-or-nothing capture atomic with the snapshot.

**Empty-player read rule (mirror `get_user_skill` 242-253, `get_user_breakdown` 268-270):**
```python
row = await self._skill_repo.fetch_snapshot_with_tier(user_id)
if row is None:
    return SkillSummaryResponse(user_id=user_id, skill_score=0.0, ... )   # all-zero, never 500
```
**Adaptation (SPEC req 7):** the three new read methods return empty/zero shapes for a user with no history — `/history` → empty points + zero summary; `/changes` → `[]`; `/changes/{id}` → None → 404. New read methods also follow the `msgspec.convert(row, ResponseStruct)` pattern (lines 257/271/280). Top-N cut (D-07): sort `diff.maps` by `|impact|` desc, top `N=5` (a module-level code constant, NOT stored) as `main_causes`, tail summed into `other_factors`; conservation `Σ main + other == delta` is exact by construction (RESEARCH:142-143).

**Scorer fns IMMUTABLE:** `_diff_weight` (77), `_map_score` (82-110), `_player_score` (113-127), `_player_breakdown` (130-161) — **do not touch** (SPEC Constraint; grep-clean acceptance criterion).

---

### `apps/api/routes/v3/skill.py` (route / controller, request-response)

**Analog:** self — existing `/skill/*` GET routes (lines 33-91); **pagination** from `apps/api/routes/v3/tournaments.py:817-818`

**GET read route — no auth opt (public read), `@get` + summary/description, delegate to service** (lines 33-51):
```python
@get(
    path="/users/{user_id:int}",
    summary="Get User Skill Summary",
    description="...",
)
async def get_user_skill(self, skill_service: SkillService, user_id: int) -> SkillSummaryResponse:
    return await skill_service.get_user_skill(user_id)
```
The three new GET routes are **public reads → NO `opt`** (matches existing skill reads; the global `scope_guard` only enforces when `required_scopes` is declared, RESEARCH:195). Controller already has `dependencies={"skill_repo": Provide(...), "skill_service": Provide(...)}` (lines 28-31) — reuse as-is.

**Pagination convention to mirror** (`tournaments.py:817-818`):
```python
limit: Annotated[int, Parameter(description="Max results", ge=1, le=100)] = 20,
offset: Annotated[int, Parameter(description="Result offset", ge=0)] = 0,
```

**404 / 4xx pattern (existing in this file, lines 126-129):**
```python
except InvalidPercentilesError as e:
    raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e)) from e
```
**Adaptation (RESEARCH §Routes):**
- `/users/{user_id:int}/history` — `window: Annotated[Window, Parameter(...)] = "all"` where `Window = Literal["7d","30d","90d","1y","all"]`. msgspec rejects an unknown value at decode → 4xx (422) automatically (A3 — satisfies "invalid window → 4xx" with no manual guard).
- `/users/{user_id:int}/changes` — same `window` param + the `limit`/`offset` pagination above.
- `/users/{user_id:int}/changes/{change_id:int}` — service returns None → controller raises `HTTPException(status_code=HTTP_404_NOT_FOUND, ...)` (mirror lines 128). Import `HTTP_404_NOT_FOUND` from `litestar.status_codes`.

---

### `apps/api/events/schemas.py` + `apps/api/events/skill.py` (event struct + listener, event-driven)

**Analog (struct):** `SkillRecomputeRequestedEvent` (`schemas.py:32-43`):
```python
class SkillRecomputeRequestedEvent(msgspec.Struct):
    reason: str | None = None
```
**Adaptation (D-10):** add `cause_category: str` (or the SDK Literal) and `actor_user_id: int | None = None`. **Keep defaults** so config/tier/nightly SYSTEM emitters and any existing emitter still construct cleanly.

**Analog (listener):** `handle_skill_recompute` (`skill.py:15-40`):
```python
@listener("skill.recompute.requested")
async def handle_skill_recompute(event: SkillRecomputeRequestedEvent, skill_service: SkillService) -> None:
    log.debug("[skill] recompute requested (reason=%s)", event.reason)
    try:
        await skill_service.recompute_all()
    except Exception:
        log.exception("[!] skill recompute (reason=%s) failed", event.reason)   # log-and-continue, no re-raise
```
**Adaptation (D-10):** build a `TriggerDescriptor` from `event.cause_category` + `event.actor_user_id` and pass it into `recompute_all(descriptor)`. Keep the log-and-continue try/except (never re-raise). Follow `log` var name + `%s` formatting + `log.exception` (CLAUDE.md logging rules).

---

### `apps/api/services/completions_service.py` (service, event-driven emit)

**Analog:** self — `_emit_skill_recompute` (lines 983-1008) + 5 call sites

**Emit helper (lines 983-1008):**
```python
@staticmethod
def _emit_skill_recompute(request, skill_service, reason: str) -> None:
    if request is None or skill_service is None:
        return
    request.app.emit(
        "skill.recompute.requested",
        SkillRecomputeRequestedEvent(reason=reason),
        skill_service=skill_service,
    )
```

**Call site (verify, lines 1094-1097):**
```python
if data.verified:
    self._emit_skill_recompute(request, skill_service, reason="skill.recompute.requested:verify")
else:
    self._emit_skill_recompute(request, skill_service, reason="skill.recompute.requested:un-verify")
```
**Adaptation (D-10):** helper signature gains `actor_user_id: int | None` + `cause_category: str` and constructs the enriched event. The five call sites — verify ~1095, un-verify ~1097, flag ~1307, unflag ~1336, moderate ~1577 — pass the completion owner `user_id` (PLAYER_ACTION). At verify/un-verify/moderate, `completion_info["user_id"]` is already in scope (fetched via `fetch_completion_for_moderation`, line 1042). **At flag/unflag (1307/1336) verify the owner id is resolvable** from `message_id`/`verification_id`; if not, add a lookup before the emit (A4 — Open Question 2, planner confirms).

**Other SYSTEM triggers (emit/call with cause=SYSTEM, actor=None):**
- `PATCH /skill/config` → `skill.py:181` calls `skill_service.recompute_all()` directly → pass a SYSTEM descriptor.
- Nightly backstop + cold-start → `app.py:152,170` call `recompute_all()` → SYSTEM descriptor (actor=None) "global recalculation".
- `PATCH /skill/tiers` → does NOT run `_do_recompute` (only `compute_tier_boundaries`); **Open Question A1** — recommend NOT writing rows (no score moved). Planner confirms.

---

### `libs/sdk/src/genjishimada_sdk/skill.py` (model, msgspec structs)

**Analog:** self — `SkillSummaryResponse` (125-146), `SkillBreakdownRow` (168-195), `SkillTiersResponse` (149-165), `SKILL_TIER_NAMES` closed-set idiom (23-46)

**Conventions (verified, lines 1-16):**
```python
from __future__ import annotations
from datetime import datetime
from msgspec import UNSET, Struct, UnsetType
__all__ = (...)   # maintained explicitly — add new structs
```
- `*Response` for reads, `*Row` for nested array elements (`SkillBreakdownRow`), `str | None` union syntax, `datetime` for timestamps.
- Closed sets: a module-level constant dict + mapper fn (`SKILL_TIER_NAMES` + `skill_tier_name`). For `cause_category` add a `Literal["PLAYER_ACTION","MAP_ENVIRONMENT","SYSTEM"]` type alias.

**`SkillBreakdownRow` shape — the model for nested array elements** (lines 187-195): plain typed fields, names mirror the scorer dict keys exactly.

**Adaptation (RESEARCH §SDK Structs — semantics locked, field names at discretion):**
- `SkillHistoryPoint` — `captured_at: datetime, skill_score: float`.
- `SkillHistoryExtremum` — `score: float, date: datetime`.
- `SkillHistorySummary` — `point_change: float, percent_change: float, best: SkillHistoryExtremum, lowest: SkillHistoryExtremum, average: float`.
- `SkillHistoryResponse` — `points: list[SkillHistoryPoint], summary: SkillHistorySummary`.
- `SkillChangeFeedItem` — `change_id: int, captured_at: datetime, delta: float, cause_category: <Literal>, description: str`.
- `SkillChangeCause` — `map: str, reason: str, impact: float`.
- `SkillChangeDetailResponse` — `previous_score, new_score, delta, percent_change: float, cause_category: <Literal>, main_causes: list[SkillChangeCause], other_factors: float`.
- Add all new struct names to `__all__`. `diff` jsonb decodes to dict via the codec; service can `msgspec.convert(row["diff"], DiffStruct)` or read the dict directly.

---

### `apps/api/tests/integration/test_skill_dashboard.py` (new test) + extend `apps/api/tests/services/test_skill_service.py`

**Analog (integration):** `apps/api/tests/integration/test_skill.py` — `_dsn` (52-53), `_recompute` (56-73), `seed` factory (76+)

**Deterministic recompute driver (`test_skill.py:56-73`):**
```python
async def _recompute(pool: asyncpg.Pool) -> None:
    await asyncio.sleep(0.1)   # let fire-and-forget background listener settle
    state = type("S", (), {"db_pool": pool})()
    service = SkillService(pool, state, SkillRepository(pool))
    await service.recompute_all()
```
**Adaptation:** for the PLAYER/MAP split call `recompute_all(descriptor)` with a single-completion descriptor; for SYSTEM/coalesced push ≥2 descriptors (or a SYSTEM descriptor) before draining, OR drive the real verify endpoint twice and assert coalesced → SYSTEM. Reuse the `seed` factory + `pytestmark = [pytest.mark.integration, pytest.mark.domain_skill]`. Conservation assertion (RESEARCH:334):
```python
assert math.isclose(sum(c["impact"] for c in body["main_causes"]) + body["other_factors"], body["delta"], abs_tol=1e-6)
```
Covers Req 1,3,4,5,6,7 (Wave 0 — file does not exist yet).

**Analog (service):** `test_skill_service.py` — `_make_service` (43-48), `_reset_guard` autouse fixture (51-58), mocked-repo assert pattern (`test_recompute_all_groups_and_replaces_snapshot`, 77-98)

**Mocked-repo assert pattern (lines 87-98):**
```python
await service.recompute_all()
repo.replace_snapshot.assert_awaited_once()
snapshot_rows = repo.replace_snapshot.await_args.args[0]
```
**Adaptation (Req 2):** assert `repo.bulk_insert_changes.await_args` carries the right `cause_category` + `diff` per user (PLAYER_ACTION actor / MAP_ENVIRONMENT bystanders / SYSTEM coalesced).

**`_reset_guard` fixture (lines 51-58) — MUST extend (RESEARCH:317):**
```python
@pytest.fixture(autouse=True)
def _reset_guard():
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
    yield
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
```
**Adaptation:** also reset the new `pending` accumulator (e.g. `svc._GUARD.pending.clear()` or `= []`) in BOTH the setup and teardown halves, or burst state leaks across tests.

---

## Shared Patterns

### Repository connection convention
**Source:** every method in `apps/api/repository/skill_repository.py` (e.g. lines 147, 165, 181)
**Apply to:** all new repo methods
```python
async def method(self, ..., *, conn: Connection | None = None) -> ...:
    _conn = self._get_connection(conn)
    ...
```
Keyword-only `conn`, `self._get_connection(conn)` to fall back to the pool. Positional `$1, $2` params only — never string interpolation (SQL-injection mitigation).

### JSONB round-trip via codec (no manual json)
**Source:** `apps/api/app.py:200-214` (`_async_pg_init`); used by `breakdown` in `replace_snapshot`
**Apply to:** the `diff` column in `bulk_insert_changes` and the drill-down read
Insert a Python dict → jsonb encoder serializes; read jsonb → decoded to Python dict. Registered on both the app pool AND the test pool/conn (`conftest.py:88,108`) — works identically in tests. **Do NOT `json.dumps`/`loads` manually** (RESEARCH §Don't Hand-Roll).

### Atomic multi-write transaction
**Source:** `apps/api/services/skill_service.py:335` (`update_tier_config`)
**Apply to:** the capture block in `_do_recompute`
```python
async with self._pool.acquire() as conn, conn.transaction():
    ...  # pass conn= to every repo call so they share one transaction
```

### Empty/zero read rule (never 500)
**Source:** `get_user_skill` (`skill_service.py:242-253`), `get_user_breakdown` (`268-270`)
**Apply to:** all three new read endpoints (SPEC req 7)
`row is None` → return the all-zero / empty shape (or None → 404 for drill-down), never raise on missing data.

### msgspec response convert
**Source:** `skill_service.py:257, 271, 280` (`msgspec.convert(row, ResponseStruct)`)
**Apply to:** all new read methods that map DB rows to `*Response` structs.

### Cause-as-text + msgspec Literal (no DB enum)
**Source:** RESEARCH:212; codebase has no `CREATE TYPE ... AS ENUM` in skill migrations
**Apply to:** `cause_category` (migration CHECK) + the SDK `Literal["PLAYER_ACTION","MAP_ENVIRONMENT","SYSTEM"]` + the `window` route param `Literal["7d","30d","90d","1y","all"]`.

## No Analog Found

None. Every file in this phase extends an existing same-domain Phase 13 file or copies a verified in-repo convention (pagination, jsonb codec, transaction pattern). The planner should NOT fall back to RESEARCH.md generic patterns — concrete analogs exist for all 9 files.

## Open Questions for Planner (from RESEARCH)

- **A1:** Should `PATCH /skill/tiers` capture history/change rows? It runs `compute_tier_boundaries` only (no `_do_recompute`, no score change). Recommendation: NO (no score moved → no history). One-line confirm.
- **A4:** Is the completion owner `user_id` resolvable at the flag/unflag emit sites (1307/1336)? verify/moderate already have it in scope; flag/unflag resolve by `message_id`/`verification_id` and may need a lookup before the emit.

## Metadata

**Analog search scope:** `apps/api/migrations/`, `apps/api/repository/`, `apps/api/services/`, `apps/api/routes/v3/`, `apps/api/events/`, `apps/api/tests/`, `libs/sdk/src/genjishimada_sdk/`
**Files scanned (read for excerpts):** `0027_skill_score.sql`, `skill_repository.py` (full), `skill_service.py` (full), `routes/v3/skill.py` (full), `routes/v3/tournaments.py:800-838`, `events/schemas.py` (full), `events/skill.py` (full), `completions_service.py:975-1104`, `libs/sdk/.../skill.py` (full), `tests/integration/test_skill.py:1-80`, `tests/services/test_skill_service.py:1-110`
**Pattern extraction date:** 2026-06-16
