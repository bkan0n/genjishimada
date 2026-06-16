# Phase 14: Skill Score Dashboard - Research

**Researched:** 2026-06-16
**Domain:** Litestar + AsyncPG + msgspec API vertical — forward-only history/attribution layer riding the Phase 13 skill recompute
**Confidence:** HIGH (all findings verified against live source in this repo; no external-package guesswork)

## Summary

This phase is **pure integration against an existing, well-structured Phase 13 codebase**. Every signature, line number, data shape, and control-flow point named in CONTEXT.md was verified against live source. There is no new library to introduce, no external dependency to install, and no ecosystem research to do — the entire stack (Litestar, AsyncPG, msgspec, pytest-databases) is already in place and exercised by passing Phase 13 tests.

The work is: (1) a new migration `0031` adding two `skill`-schema tables; (2) wiring history+change capture into the single `_do_recompute` routine, reading the previous snapshot *before* `replace_snapshot` truncates; (3) threading a typed `cause_category` + `actor_user_id` through `SkillRecomputeRequestedEvent` and an accumulator on `_RecomputeGuard`; (4) three GET routes on the existing `SkillController`; (5) new SDK structs; (6) integration + service tests mirroring the existing `_recompute(pool)` test driver.

**The single most important verified finding:** conservation (`Σ impact == delta`) is **mathematically guaranteed at write time** with zero special handling, because `_player_score` and `_player_breakdown` decompose the score identically — `skill_score == Σ contribution` is already asserted by the passing Phase 13 test `test_breakdown_contributions_sum_to_total`. Since `delta = new_score − prev_score = Σ new_contrib − Σ prev_contrib = Σ (new_contrib − prev_contrib) = Σ impact`, the D-04 diff array conserves exactly by construction. The 1e-6 tolerance in SPEC req 5 is float slack, not a design risk.

**Primary recommendation:** Read the previous snapshot inside `_do_recompute` *before* calling `replace_snapshot`, build per-user `score_history` + `score_change` rows in the service (the new breakdown is already in hand), pass them to two new repository `executemany` bulk-insert methods, and persist them on the **same connection/transaction** as `replace_snapshot` so capture is atomic with the snapshot it describes. Decide the per-user `cause_category` from the `_RecomputeGuard` descriptor accumulator immediately before `_do_recompute`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| History/change capture | API / Service (`_do_recompute`) | Database (bulk insert) | Rides the one Python scorer routine; conservation math is service-side (D-05) |
| Cause attribution decision | API / Service (`_RecomputeGuard` accumulator) | Event payload (`SkillRecomputeRequestedEvent`) | Typed descriptor, no string parsing (D-10) |
| Diff/impact computation | API / Service | — | New breakdown already in hand from `_player_breakdown`; cheap prev-vs-new pass (D-04) |
| History/feed/drill-down reads | API / Service → Repository | Database (indexed queries) | Three-layer house pattern; window filter + ownership check in SQL |
| Top-N cut + other_factors rollup | API / Service (read time) | — | Tunable code constant `N=5`, not stored (D-06/D-07) |
| Window→interval mapping | API / Service or SQL `now() - interval` | — | Five closed values; Literal-validated |
| Response serialization | SDK msgspec structs | — | `*Response` structs; `diff` jsonb round-trips via existing codec |

## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01 .. D-10)
- **D-01:** Two tables — `skill.score_history` (lean time-series, PK `(user_id, captured_at)`) and `skill.score_change` (rich: `change_id bigserial PK, user_id, captured_at, previous_score, new_score, delta, cause_category text, reason text, diff jsonb`, index on `(user_id, captured_at DESC)`).
- **D-02:** One row per user-with-data per recompute in **both** tables, even on delta=0. All rows from one recompute share the single `captured_at` = the existing `computed_at = datetime.now(timezone.utc)` minted at the top of `_do_recompute`.
- **D-03:** Retention unbounded, forward-only. No pruning this phase.
- **D-04:** `score_change.diff` (jsonb) stores a precomputed all-maps impact array `{"maps":[{"map","prev","new","impact"}, ...]}`, `impact = new_contribution − prev_contribution`. `Σ impact == delta` exactly at write time.
- **D-05:** `_do_recompute` MUST read the previous snapshot (score + breakdown) **before** `replace_snapshot` TRUNCATEs. Diff computed in service; repo gets bulk-insert methods. Rides the single recompute routine.
- **D-06:** Store ALL per-map impacts; apply top-N cut at READ time (tunable, no migration to re-cut).
- **D-07:** `/changes/{change_id}` sorts `diff.maps` by `|impact|` desc, lists top **5** as `main_causes {map, reason, impact}`, rolls the tail into one `other_factors` scalar. `N=5` is a code constant.
- **D-08:** Single clean completion trigger → actor (completion owner) = `PLAYER_ACTION`; every other user-with-data = `MAP_ENVIRONMENT` (incl. delta=0 bystanders).
- **D-09:** SYSTEM triggers (`PATCH /skill/config`, `PATCH /skill/tiers`, nightly backstop, cold-start auto-fill, any coalesced burst) → every user `SYSTEM` "global recalculation".
- **D-10:** Threading = typed event fields (`cause_category` + `actor_user_id`) on `SkillRecomputeRequestedEvent` + `_RecomputeGuard` accumulates pending descriptors. Decision: exactly ONE completion descriptor with actor → PLAYER/MAP split; 2+ descriptors OR any SYSTEM present → all SYSTEM. The five `_emit_skill_recompute` sites pass the completion owner's `user_id`.

### Claude's Discretion
- Pagination: `limit` (ge=1 le=100 default 20) + `offset` (ge=0) — mirror `routes/v3/tournaments.py:817`. No cursor pagination.
- Exact msgspec struct field layouts for the three response shapes; struct/field names beyond the locked semantic set.
- Exact column types/names beyond the D-01 sketch; index names; `cause_category` as `text` + CHECK or `text` + msgspec `Literal` (lean toward CHECK/Literal, the codebase avoids DB enums).
- The descriptor struct shape inside `_RecomputeGuard`; exact field names on the enriched event.
- Window→interval mapping (relative to `now()`); summary anchoring (already specified in SPEC req 3).
- Test-mode triggering pattern (in-process, not RabbitMQ-gated).

### Deferred Ideas (OUT OF SCOPE)
- Retention pruning / downsampling of either table.
- Website dashboard UI; Discord `/skill` history surface.
- Cursor pagination.
- Manual admin recompute / on-demand recovery endpoint.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| Req 1 | Timestamped history capture per recompute | `_do_recompute` already iterates `by_user`; add a `score_history` row per user using the existing `computed_at` (skill_service.py:210). New repo `bulk_insert_history`. |
| Req 2 | Per-change record (cause + delta + diff) | Read prev snapshot before `replace_snapshot` (skill_repository.py:185); build `score_change` rows in service; `cause_category` from `_RecomputeGuard` descriptor. |
| Req 3 | History + summary endpoint | New GET on `SkillController` (skill.py:23); window→`now() - interval` SQL filter; summary math in service (anchoring per SPEC req 3). |
| Req 4 | Recent-changes feed (paginated) | GET with `limit`/`offset` (tournaments.py:817 convention); SQL `ORDER BY captured_at DESC` over `(user_id, captured_at DESC)` index. |
| Req 5 | Change drill-down | GET `/changes/{change_id}`; ownership check `WHERE change_id=$1 AND user_id=$2`; sort `diff.maps` by `|impact|`, top-5 + `other_factors`. Conservation exact by construction. |
| Req 6 | Time-window filtering | Five-value Literal `window`; reject unknown with 4xx (msgspec Literal decode or explicit guard). |
| Req 7 | Empty/zero-eligible handling | No history rows → 200 empty points + zero summary (`/history`), empty feed (`/changes`), 404 (`/changes/{id}`). Mirrors D-07 empty-player rule already used by `get_user_skill`. |

## Recompute Control Flow (verified line-for-line)

**File:** `apps/api/services/skill_service.py`

### `_RecomputeGuard` (lines 47-67)
```python
class _RecomputeGuard:
    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None   # created lazily so it binds to the running loop
        self.rerun_requested = False
    @property
    def lock(self) -> asyncio.Lock: ...           # lazy single lock

_GUARD = _RecomputeGuard()                          # module scope — one per process (NOT per-request)
```
- Fields today: `_lock`, `rerun_requested`. **D-10 adds a descriptor accumulator** (e.g. `pending: list[TriggerDescriptor]`) here.
- The guard is module-scope because Litestar builds a fresh `SkillService` per request via DI — a per-instance lock would never coalesce across requests. Any new accumulator field MUST also live at module scope.

### `recompute_all` (lines 178-199) — the coalescing burst collapse
```python
async def recompute_all(self) -> None:
    _GUARD.rerun_requested = True
    if _GUARD.lock.locked():
        return                                     # a rebuild is running; it will pick up the flag
    async with _GUARD.lock:
        while _GUARD.rerun_requested:
            _GUARD.rerun_requested = False
            await self._do_recompute()
```
**How a burst collapses:** first caller acquires the lock and enters the `while` loop. Concurrent callers find `lock.locked()` True, set `rerun_requested=True`, and return immediately (fire-and-forget). The holder loops once more, picking up the flag, and runs a *second* `_do_recompute`. Net: N triggers → 1 or 2 actual rebuilds (asserted by `test_recompute_all_collapses_concurrent_bursts`: `assert started <= 2`).

**D-10 implication — where the cause decision must happen:** `recompute_all` is the natural place to push the incoming descriptor onto `_GUARD.pending` (before the `lock.locked()` early return, so a coalesced trigger still records its descriptor). Then *inside the lock, before each `_do_recompute`*, drain `_GUARD.pending` and compute the per-recompute cause policy:
- exactly 1 pending descriptor with `actor_user_id` set → `(PLAYER_ACTION, actor_id)`
- ≥2 pending OR any `SYSTEM` descriptor → `(SYSTEM, "global recalculation")`
Pass the resolved policy into `_do_recompute`. Note: because the holder may run `_do_recompute` twice (collapsed rerun), draining `pending` per iteration is correct — descriptors that arrived during the first rebuild are evaluated for the second. **Landmine:** if you drain `pending` once before the loop instead of per-iteration, a coalesced burst that arrives mid-rebuild loses its SYSTEM-promotion. Drain inside the `while`.

### `_do_recompute` (lines 201-230) — the capture wiring site (D-05)
```python
async def _do_recompute(self) -> None:
    w = msgspec.convert(await self._skill_repo.fetch_weights(), Weights)
    rows = await self._skill_repo.fetch_skill_inputs()
    by_user: dict[int, list[dict]] = defaultdict(list)
    for r in rows: by_user[r["user_id"]].append(r)
    computed_at = datetime.now(timezone.utc)        # (a) computed_at minted HERE — reuse as captured_at (D-02)
    snapshot_rows: list[dict] = []
    for user_id, urows in by_user.items():
        snapshot_rows.append({ ... "breakdown": _player_breakdown(urows, w), "computed_at": computed_at })
    await self._skill_repo.replace_snapshot(snapshot_rows)   # (c) TRUNCATE+rebuild — prev snapshot GONE after this
    await self._skill_repo.compute_tier_boundaries()
```

**The three critical points (D-05):**
- **(a) `computed_at` minted — line 210.** This is the single `captured_at` for all history+change rows of this recompute (D-02). Do NOT mint a second timestamp.
- **(b) Prev snapshot still readable — anywhere before line 224.** Add a `prev = await self._skill_repo.fetch_all_snapshots()` call near the top of `_do_recompute` (a new bulk read returning `{user_id: {"skill_score", "breakdown"}}`). The current `fetch_snapshot(user_id)` is per-user; a bulk variant avoids ~261 round-trips.
- **(c) `replace_snapshot` TRUNCATEs — skill_repository.py:201 (`TRUNCATE skill.snapshot` inside the method's transaction).** After this call the previous scores are unrecoverable. **All prev reads MUST happen before line 224.**

**Recommended sequence inside `_do_recompute`:**
1. fetch weights, inputs, group by_user, mint `computed_at` (existing).
2. **NEW:** `prev = await self._skill_repo.fetch_all_snapshots()` (before replace).
3. build `snapshot_rows` with `_player_breakdown` (existing).
4. **NEW:** for each user, compute `previous_score = prev.get(uid, {}).get("skill_score", 0.0)`, build the `diff.maps` array from prev breakdown vs new breakdown (`contribution` field), assemble `score_history` + `score_change` rows.
5. `await self._skill_repo.replace_snapshot(snapshot_rows)` (existing).
6. **NEW:** `await self._skill_repo.bulk_insert_history(history_rows)` and `bulk_insert_changes(change_rows)`.
7. `compute_tier_boundaries` (existing).

**Atomicity note:** `replace_snapshot` opens its own transaction internally (skill_repository.py:200) and acquires its own connection if passed a Pool. To make capture atomic with the snapshot, either (a) acquire one connection in `_do_recompute`, open one transaction, and pass `conn=` to `replace_snapshot` + the two new bulk inserts + `compute_tier_boundaries` (all already accept `conn`), or (b) accept that the inserts are a separate transaction (acceptable — capture failure is logged and self-heals next recompute). Recommend (a) for a clean all-or-nothing recompute; it matches the `update_tier_config` pattern at skill_service.py:335 (`async with self._pool.acquire() as conn, conn.transaction():`).

### Scorer functions — IMMUTABLE this phase
- `_diff_weight` (77), `_map_score` (82-110), `_player_score` (113-127), `_player_breakdown` (130-161). **Do not touch.** SPEC Constraint + acceptance criterion "grep clean; existing skill tests still pass."

### `_player_breakdown` return shape (the `contribution` field — drives D-04)
Each dict (skill_service.py:148-159): `map_name, difficulty, raw, fully_verified, medal, wr, raw_score, contribution, rank`. **`contribution = raw_score / (rank ** gamma)`** — the gamma-decayed value. D-04's `impact = new.contribution − prev.contribution`. Key for matching maps across snapshots: use `map_name` (the breakdown does not carry `map_id`; `map_name` falls back to `code` then `map {map_id}`). **Landmine:** if two of a user's maps share a display name the join is ambiguous — extremely unlikely but worth a stable key. Consider adding `map_id` to the breakdown ONLY if the planner judges it safe (it changes the stored JSONB shape and the SDK `SkillBreakdownRow` — that touches Phase 13 surface; prefer matching on `map_name` to stay byte-for-byte clean, OR confirm with user). **Default: match on `map_name`.**

### Conservation proof (verified)
`_player_score` (line 127) = `sum(s / i**gamma for i,s in enumerate(sorted_scores, 1))`. `_player_breakdown` (line 157) emits `contribution = s / (i**gamma)` over the **same sorted scores with the same 1-based rank**. Therefore `skill_score == Σ contribution` exactly (modulo float assoc). This is the live invariant asserted by `test_breakdown_contributions_sum_to_total` (test_skill.py:448, `math.isclose(..., 1e-6)`). Hence `delta = Σ new_contrib − Σ prev_contrib = Σ impact` — **conservation is free**; the residual `other_factors` (tail beyond top-5) is exactly `delta − Σ(top5 impact)`.

## Repository Surface (verified)

**File:** `apps/api/repository/skill_repository.py`

| Method | Lines | Signature | Notes |
|--------|-------|-----------|-------|
| `fetch_skill_inputs` | 132-149 | `(*, conn=None) -> list[dict]` | Runs `SKILL_INPUT_QUERY`, drops suspicious in Python |
| `snapshot_is_empty` | 151-166 | `(*, conn=None) -> bool` | `NOT EXISTS` probe |
| `fetch_snapshot` | 168-183 | `(user_id, *, conn=None) -> dict \| None` | Single-user; `breakdown` decodes via jsonb codec |
| `replace_snapshot` | 185-229 | `(rows, *, conn=None) -> None` | **TRUNCATE + executemany** in one transaction (line 201) |
| `fetch_weights` | 231-249 | `(*, conn=None) -> dict` | The 9 weight columns |
| `update_weights` | 251-280 | allow-list SET clause | |
| `fetch_snapshot_with_tier` | 362-395 | `(user_id, *, conn=None)` | width_bucket tier + percentile |

**Bulk-insert house style (verified):** `replace_snapshot` uses **`executemany`** with a positional-tuple list comprehension (skill_repository.py:204-222). This is the established bulk pattern — no COPY, no `unnest`. **The two new bulk-insert methods should mirror this exactly.** All repo methods take `*, conn: Connection | None = None` and call `self._get_connection(conn)`; new methods must too.

**`skill.snapshot` row shape (migration 0027, lines 16-25):** `user_id bigint PK, skill_score double precision, maps_cleared integer, video_clears integer, hardest_raw double precision, breakdown jsonb DEFAULT '[]', computed_at timestamptz DEFAULT now()`.

**New methods needed:**
- `fetch_all_snapshots(*, conn=None) -> dict[int, dict]` — read all `(user_id, skill_score, breakdown)` rows BEFORE replace. `breakdown` decodes via the jsonb codec automatically.
- `bulk_insert_history(rows, *, conn=None)` — `executemany` into `skill.score_history`.
- `bulk_insert_changes(rows, *, conn=None)` — `executemany` into `skill.score_change`; `diff` is a Python dict serialized by the jsonb encoder (same as `breakdown`).
- `fetch_history(user_id, since, *, conn=None)` — `WHERE user_id=$1 AND captured_at >= $2 ORDER BY captured_at`.
- `fetch_changes(user_id, since, limit, offset, *, conn=None)` — `ORDER BY captured_at DESC LIMIT $.. OFFSET $..`.
- `fetch_change(user_id, change_id, *, conn=None) -> dict | None` — `WHERE change_id=$1 AND user_id=$2` (ownership check → None → route 404).

## Event + Trigger Threading (verified)

**`SkillRecomputeRequestedEvent`** — `apps/api/events/schemas.py:32-43`. Today only `reason: str | None = None`. **D-10 adds** `cause_category: str` (or `Literal`) and `actor_user_id: int | None = None`. Keep defaults so existing/SYSTEM emitters still construct cleanly.

**Listener** — `apps/api/events/skill.py:15-40`. `@listener("skill.recompute.requested")`, signature `(event, skill_service)`. Currently logs `event.reason` then `await skill_service.recompute_all()` inside try/except (log-and-continue, never re-raise). **D-10:** pass a descriptor built from `event.cause_category` + `event.actor_user_id` into `recompute_all(descriptor)`.

**`_emit_skill_recompute`** — `completions_service.py:983-1008` (static helper, fire-and-forget via `request.app.emit(...)`). Five call sites:
| Site | Line | Current reason | D-10 change |
|------|------|----------------|-------------|
| verify | 1095 | `:verify` | pass actor = completion owner `user_id`, cause PLAYER_ACTION |
| un-verify | 1097 | `:un-verify` | pass actor = owner, PLAYER_ACTION |
| flag | 1307 | `:flag` | pass actor = owner, PLAYER_ACTION |
| unflag | 1336 | `:unflag` | pass actor = owner, PLAYER_ACTION |
| moderate | 1577 | `:moderate` | pass actor = owner, PLAYER_ACTION |

`completion_info["user_id"]` is the completion owner and is already in scope at every site (fetched via `fetch_completion_for_moderation` at 1042/1461; for flag/unflag the owner is resolvable from `data.message_id`/`verification_id` — verify whether the owner id is readily available at the flag/unflag sites or must be fetched). **The helper signature gains `actor_user_id` + `cause_category`** and constructs the enriched event. The five route call sites already thread `request` + `skill_service` (completions.py:204, 255, 275, 382).

**Other SYSTEM trigger sites (emit/call with cause=SYSTEM, actor=None):**
- `PATCH /skill/config` → `skill.py:181` calls `skill_service.recompute_all()` directly (not via event). Pass a SYSTEM descriptor.
- `PATCH /skill/tiers` → does NOT call `recompute_all` (only `compute_tier_boundaries` via `update_tier_config`, skill_service.py:335). **Per D-09 it is a SYSTEM trigger** — but note it currently writes no snapshot, so it produces no history/change rows today. Confirm with planner whether `/skill/tiers` should emit a history/change capture: per D-09 it is listed as SYSTEM, but it does not run `_do_recompute`. **Open question A1 below.**
- Nightly backstop + cold-start → `app.py:152, 170` call `recompute_all()` directly. Pass SYSTEM descriptor (actor=None) — these become "global recalculation".

## Route + Controller Patterns (verified)

**`SkillController`** — `apps/api/routes/v3/skill.py:23`. `path="/skill"`, `tags=["Skill"]`, `dependencies={"skill_repo": Provide(provide_skill_repository), "skill_service": Provide(provide_skill_service)}`. Existing GET routes (`/users/{user_id:int}`, `/users/{user_id:int}/breakdown`, `/tiers`, `/config`) carry **NO auth opt** → public reads (the global `scope_guard` only enforces when `required_scopes` is declared). The three new GET routes are public reads → **no `opt`** (matches existing skill reads). Only the PATCH routes carry `opt={"required_scopes": {"skill:admin"}}`.

**Pagination convention** — `apps/api/routes/v3/tournaments.py:817-818`:
```python
limit: Annotated[int, Parameter(description="Max results", ge=1, le=100)] = 20,
offset: Annotated[int, Parameter(description="Result offset", ge=0)] = 0,
```
Mirror this exactly on `/changes`.

**Window parameter:** declare as `Annotated[Literal["7d","30d","90d","1y","all"], Parameter(...)]` so msgspec rejects an unknown value at decode → 400/422 (satisfies "invalid window → 4xx" without manual validation). Verify Litestar surfaces a Literal mismatch as 4xx (it does via msgspec strict decode — 422). If a 400 is preferred, validate explicitly in the handler and raise `HTTPException(HTTP_400_BAD_REQUEST)` as the PATCH routes do (skill.py:129).

**404 pattern:** drill-down returns 404 for unknown/foreign `change_id`. Follow the existing `HTTPException(status_code=..., detail=...)` raise pattern (skill.py:128). Service returns None → controller raises 404.

## Migration Conventions (verified)

- **Next number is `0031`** (latest applied migration is `0030_rank_tournament_by_video_within_tier.sql`).
- **DDL style** (from 0027/0028): wrap in `BEGIN; ... COMMIT;`, `CREATE SCHEMA IF NOT EXISTS skill;`, `CREATE TABLE IF NOT EXISTS skill.<name> (...)`, idempotent seeds via `INSERT ... SELECT ... WHERE NOT EXISTS`. Header comment block (`-- Migration:`, `-- Description:`, `-- Date:`).
- **Small closed sets use `text` + CHECK, never Postgres enums** — confirmed (the codebase has no `CREATE TYPE ... AS ENUM` in skill migrations; `gamma >= 0.5` is a `CHECK`, 0027:42). For `cause_category` use `cause_category text NOT NULL CHECK (cause_category IN ('PLAYER_ACTION','MAP_ENVIRONMENT','SYSTEM'))` paired with an msgspec `Literal` in the SDK.
- **Type idioms:** `bigint` for user ids, `double precision` for scores, `timestamptz` for timestamps, `jsonb` for the diff, `bigserial`/`integer GENERATED ALWAYS AS IDENTITY` for synthetic PKs (0027:32 / 0028:22 use `integer GENERATED ALWAYS AS IDENTITY`; D-01 says `bigserial` for `change_id` — both are house-acceptable; `bigserial` is fine given unbounded growth).
- **Index naming:** the existing skill migrations declare no explicit indexes beyond PKs. Use Postgres default naming or explicit `CREATE INDEX skill_score_change_user_captured_idx ON skill.score_change (user_id, captured_at DESC);`. PK `(user_id, captured_at)` on `score_history` covers history reads.
- **Migrations are applied verbatim in tests** by `_apply_sql_dir` (conftest.py:58-67): every `*.sql` in `apps/api/migrations/` is read and `conn.execute(sql_text, prepare=False)` in sorted order at session start. So `0031` applies on the fresh test DB automatically — the acceptance criterion "applies cleanly on a fresh test DB" is satisfied by it being valid SQL.

## SDK Structs (verified)

**File:** `libs/sdk/src/genjishimada_sdk/skill.py`. Conventions:
- `from msgspec import UNSET, Struct, UnsetType`; `from __future__ import annotations`.
- `*Response` for reads, `*Request` for writes, `*Row` for nested array elements (`SkillBreakdownRow`).
- Union syntax `str | None`; PATCH optionals `float | UnsetType = UNSET`.
- Closed sets as a module-level constant dict + a mapper fn (`SKILL_TIER_NAMES` + `skill_tier_name`); for `cause_category` add a `Literal["PLAYER_ACTION","MAP_ENVIRONMENT","SYSTEM"]` type alias.
- `__all__` is maintained explicitly — add new structs to it.
- `datetime` imported `from datetime import datetime` for timestamp fields (skill.py:3).

**New structs needed (field names at Claude's discretion, semantics locked):**
- `SkillHistoryPoint` — `captured_at: datetime, skill_score: float`.
- `SkillHistorySummary` — `point_change: float, percent_change: float, best: SkillHistoryExtremum, lowest: SkillHistoryExtremum, average: float` (extremum = `{score: float, date: datetime}`).
- `SkillHistoryResponse` — `points: list[SkillHistoryPoint], summary: SkillHistorySummary`.
- `SkillChangeFeedItem` — `change_id: int, captured_at: datetime, delta: float, cause_category: <Literal>, description: str`.
- `SkillChangeDetailResponse` — `previous_score, new_score, delta, percent_change: float, cause_category, main_causes: list[SkillChangeCause], other_factors: float`. `SkillChangeCause = {map: str, reason: str, impact: float}`.

The stored `diff` jsonb decodes to a typed structure via the existing codec — the service can `msgspec.convert(row["diff"], DiffStruct)` for the drill-down (or read the dict directly; the codec already returns a Python dict).

## JSONB Codec (verified)

`apps/api/app.py:200-214`, `_async_pg_init`:
```python
await conn.set_type_codec("numeric", encoder=str, decoder=float, schema="pg_catalog", format="text")
await conn.set_type_codec("jsonb", encoder=_jsonb_encoder, decoder=_jsonb_decoder, schema="pg_catalog", format="text")
# _jsonb_encoder: msgspec.json.encode(value).decode() (passes str through)
# _jsonb_decoder: msgspec.json.decode(value)
```
- The codec is registered on **both** the app pool (`PoolConfig(dsn=dsn, init=_async_pg_init)`, app.py:249) **and** the test pool/conn (conftest.py:88, 108). So the `diff` jsonb round-trips as a Python dict on write (insert a dict → encoded) and read (decoded to dict) in both runtime and tests — exactly like `breakdown`. No manual JSON handling.
- The `numeric → float` codec means any `double precision` column reads as a Python `float` (scores already do).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bulk insert of N rows | A loop of single INSERTs | `executemany` + positional-tuple list (skill_repository.py:204) | House style; one round-trip batch |
| JSONB (de)serialization for `diff` | Manual `json.dumps`/`loads` | The existing jsonb codec | Already registered on every pool/conn |
| Coalescing concurrent recomputes | A new lock/flag scheme | The existing `_RecomputeGuard` + add a `pending` accumulator | One per process; already correct + tested |
| Conservation enforcement | Read-time recompute or rebalancing | Store `impact = new_contrib − prev_contrib` at write | `Σ impact == delta` exact by the scorer's own decomposition |
| Window validation | Hand-rolled string parsing of `reason` | msgspec `Literal` param (auto 4xx) + typed event fields (D-10) | Typed; no fragile suffix parsing |
| Tier/score math | Any change to `_map_score`/`_player_score` | Leave untouched; read `contribution` from `_player_breakdown` | Scorer immutability constraint |

**Key insight:** Everything this phase needs (bulk insert, jsonb codec, coalescing guard, the score decomposition) already exists and is tested. The phase is wiring, not invention.

## Common Pitfalls

### Pitfall 1: Reading the previous snapshot AFTER replace_snapshot truncates
**What goes wrong:** `previous_score` and prev breakdown come back empty/zero for every user → all deltas equal the new score, all `prev` impacts are 0.
**Why:** `replace_snapshot` runs `TRUNCATE skill.snapshot` (skill_repository.py:201) inside its own transaction; once called the prior state is gone.
**How to avoid:** Call `fetch_all_snapshots()` near the top of `_do_recompute`, before line 224. Capture prev into a `{user_id: {...}}` dict.
**Warning sign:** first-ever recompute is fine (prev empty is correct), but the SECOND recompute shows delta == new_score for unchanged users.

### Pitfall 2: Draining the descriptor accumulator outside the rerun `while` loop
**What goes wrong:** A coalesced burst that arrives mid-rebuild is evaluated against a stale/empty accumulator → mis-tagged PLAYER_ACTION instead of SYSTEM.
**Why:** `recompute_all` may run `_do_recompute` twice (the rerun); descriptors arriving during the first run belong to the second.
**How to avoid:** Drain `_GUARD.pending` and compute the cause policy *inside* the `while _GUARD.rerun_requested:` loop, once per `_do_recompute` call. Append the descriptor in `recompute_all` *before* the `lock.locked()` early return.
**Warning sign:** the "coalesced burst → SYSTEM" test passes alone but fails when interleaved.

### Pitfall 3: Per-user round-trip to read prev snapshot (~261 queries)
**What goes wrong:** Using the existing `fetch_snapshot(user_id)` in a loop adds ~261 sequential queries to every recompute.
**How to avoid:** One bulk `fetch_all_snapshots()` read.

### Pitfall 4: Matching maps across snapshots on an ambiguous key
**What goes wrong:** If a user has two maps with the same display `map_name`, the prev↔new contribution join double-counts or drops one.
**How to avoid:** Match on `map_name` (the breakdown's stable display key); the planner may consider whether `map_id` belongs in the breakdown, but adding it changes Phase-13 SDK surface — default to `map_name` and treat collisions as out-of-scope-rare.

### Pitfall 5: Forgetting that `/skill/tiers` PATCH does not run `_do_recompute`
**What goes wrong:** D-09 lists `PATCH /skill/tiers` as a SYSTEM trigger, but it only re-derives boundaries (no snapshot rebuild) → no history/change rows are produced today.
**How to avoid:** Confirm intent (Open Question A1). Either (a) leave it as-is (it changes no scores, so capturing zero-delta rows for everyone is arguably noise) or (b) explicitly emit a SYSTEM recompute. Lean toward (a): tier percentiles do not move `skill_score`, so there is no score history to record.

### Pitfall 6: Writing capture in a transaction separate from replace_snapshot
**What goes wrong:** A crash between `replace_snapshot` and the bulk inserts leaves the snapshot updated but history/change missing for that recompute.
**How to avoid:** Acquire one connection + transaction in `_do_recompute` and pass `conn=` to all four repo calls (all accept it). Mirrors `update_tier_config` (skill_service.py:335).

## Runtime State Inventory

> This is a greenfield-within-existing-schema addition (two new tables), not a rename/refactor. No stored data is being renamed, no live-service config or OS-registered state references a changing string, no secrets/env vars change, no build artifacts carry a stale name.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — two NEW tables (`skill.score_history`, `skill.score_change`); nothing renamed. Forward-only, no backfill (SPEC). | None |
| Live service config | None — no external service config references this phase's strings. | None |
| OS-registered state | None — nightly recompute is an app-side lifespan task (app.py:111), not a pg_cron/OS job. | None |
| Secrets/env vars | None. | None |
| Build artifacts | None. | None |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5+ with pytest-asyncio (auto mode), pytest-xdist (8 workers), pytest-databases[postgres] |
| Config file | `apps/api/pyproject.toml` (pytest config) |
| Quick run command | `just test-api` (or `uv run pytest apps/api/tests/services/test_skill_service.py -x`) |
| Full suite command | `just test-api` |
| Migration application | `conftest.py:_apply_sql_dir` applies every `migrations/*.sql` in sorted order at session start — `0031` auto-applies on the fresh test DB |

### How recompute is driven in tests (verified)
- Skill recompute is **in-process, NOT RabbitMQ-gated** by `X-PYTEST-ENABLED=1` (test_skill.py:9, events/skill.py:21). Tests drive it deterministically via the `_recompute(pool)` helper (test_skill.py:56-73): it sleeps 0.1s to let the fire-and-forget background listener settle, then runs `SkillService(pool, state, SkillRepository(pool)).recompute_all()` on the dedicated test pool as the authoritative last-writer.
- **For Phase 14:** to assert the PLAYER/MAP split, call `recompute_all(descriptor)` directly with a single-completion descriptor; to assert the SYSTEM/coalesced path, push ≥2 descriptors (or a SYSTEM descriptor) before draining, or call via the real verify endpoint twice and assert the coalesced result is SYSTEM. The service-level test can mock the repo (test_skill_service.py:43 `_make_service`) and assert the `bulk_insert_changes` call args carry the right `cause_category` + `diff`.
- **Guard reset between tests:** the `_reset_guard` autouse fixture (test_skill_service.py:51-59) resets `_GUARD._lock` and `_GUARD.rerun_requested` — **extend it to also reset the new `pending` accumulator** or burst state leaks across tests.

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Command | File Exists? |
|-----|----------|-----------|---------|-------------|
| Req 1 | ≥2 history rows w/ distinct captured_at after 2 recomputes; none pre-rollout | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ Wave 0 |
| Req 2 | verify → PLAYER_ACTION delta row; config/nightly → SYSTEM; coalesced → SYSTEM "global recalculation" | integration + service | same / `tests/services/test_skill_service.py` | ❌ Wave 0 (extend existing service test) |
| Req 3 | known 30d fixture → correct best/lowest/average + point/percent change; invalid window → 4xx; empty user → 200 empty+zero | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ Wave 0 |
| Req 4 | feed desc by captured_at; limit bounds page; window respected; empty user empty feed | integration | same | ❌ Wave 0 |
| Req 5 | `sum(main_causes.impact) + other_factors == delta` within 1e-6; foreign change_id → 404 | integration + service | same | ❌ Wave 0 |
| Req 6 | each of 5 windows in-range only; `all` returns full; unknown → 4xx | integration | same | ❌ Wave 0 |
| Req 7 | empty user: 200 empty/zero (history), empty feed, 404 (change_id); never 500 | integration | same | ❌ Wave 0 |
| Constraint | Phase 13 scorer/weight/tier unchanged | regression | existing `test_skill.py` + `test_skill_scorer.py` must stay green | ✅ exists |

### Conservation assertion (Req 5) — fixture shape
Seed a user, run two recomputes that change the field (verify a faster run as in `test_field_relativity_second_player_updates`, test_skill.py:258), fetch the `change_id` from `/changes`, GET `/changes/{change_id}`, then:
```python
assert math.isclose(sum(c["impact"] for c in body["main_causes"]) + body["other_factors"], body["delta"], abs_tol=1e-6)
```
Empty-user assertions: `GET /history` → 200 `{"points": [], "summary": {all zeros}}`; `GET /changes` → 200 `[]`; `GET /changes/{any}` → 404. Window assertions: insert history rows at known `captured_at` offsets, assert each window returns only in-range points.

### Sampling Rate
- **Per task commit:** `uv run pytest apps/api/tests/services/test_skill_service.py apps/api/tests/integration/test_skill_dashboard.py -x`
- **Per wave merge:** `just test-api` (full parallel suite)
- **Phase gate:** Full suite green + `just lint-api` + `just lint-sdk` clean before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/integration/test_skill_dashboard.py` — covers Req 1,3,4,5,6,7 (reuse the `seed` factory + `_recompute` helper pattern from `test_skill.py`).
- [ ] Extend `tests/services/test_skill_service.py` — covers Req 2 cause attribution (PLAYER/MAP split, coalesced→SYSTEM) with mocked repo; extend `_reset_guard` for the new accumulator.
- [ ] No new framework install — pytest infra fully present.

## Environment Availability

> All dependencies are already present in the repo and exercised by passing Phase 13 tests. No new external dependency is introduced by this phase.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Litestar | Routes/controller | ✓ | >=2.16.0 | — |
| asyncpg (litestar-asyncpg) | Repository | ✓ | >=0.4.0 | — |
| msgspec | SDK structs + jsonb codec | ✓ | >=0.19.0 | — |
| pytest + pytest-databases[postgres] | Integration tests | ✓ | 8.3.5+ / 0.14.0+ | — |
| PostgreSQL (Docker, test) | Migration + queries | ✓ (pytest-databases provisions) | 17 | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Code Examples

### Bulk insert mirroring the house pattern (skill_repository.py:204)
```python
# Source: apps/api/repository/skill_repository.py:204-222 (replace_snapshot)
await c.executemany(
    """
    INSERT INTO skill.score_change
        (user_id, captured_at, previous_score, new_score, delta, cause_category, reason, diff)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """,
    [(r["user_id"], r["captured_at"], r["previous_score"], r["new_score"],
      r["delta"], r["cause_category"], r["reason"], r["diff"]) for r in rows],
)
# r["diff"] is a Python dict; the jsonb encoder (app.py:207) serializes it automatically.
```

### Atomic capture transaction (mirrors skill_service.py:335)
```python
async with self._pool.acquire() as conn, conn.transaction():
    prev = await self._skill_repo.fetch_all_snapshots(conn=conn)
    # ... build snapshot_rows, history_rows, change_rows ...
    await self._skill_repo.replace_snapshot(snapshot_rows, conn=conn)
    await self._skill_repo.bulk_insert_history(history_rows, conn=conn)
    await self._skill_repo.bulk_insert_changes(change_rows, conn=conn)
    await self._skill_repo.compute_tier_boundaries(conn=conn)
```

### Window param (auto 4xx on invalid value)
```python
from typing import Literal
from litestar.params import Parameter
from typing import Annotated

Window = Literal["7d", "30d", "90d", "1y", "all"]

@get(path="/users/{user_id:int}/history")
async def get_history(
    self, skill_service: SkillService, user_id: int,
    window: Annotated[Window, Parameter(description="Time window")] = "all",
) -> SkillHistoryResponse: ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Score has no history; `skill.snapshot` overwritten each recompute | Forward-only `score_history` + `score_change` capture | This phase | Past scores still unrecoverable (no backfill); accrual starts now |
| `SkillRecomputeRequestedEvent.reason` logged only | Typed `cause_category` + `actor_user_id` drive per-user attribution | This phase | No string parsing; PLAYER/MAP/SYSTEM tagging |

**Deprecated/outdated:** None relevant — the Phase 13 design is current and unchanged.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `PATCH /skill/tiers` should NOT produce history/change rows (it re-derives boundaries only, changes no `skill_score`), despite D-09 listing it as a SYSTEM trigger | Event threading / Pitfall 5 | Low — if user wants tier retunes logged, add a SYSTEM recompute emit. Confirm at discuss/plan. |
| A2 | Cross-snapshot map matching keys on `map_name` (breakdown has no `map_id`) | Recompute control flow / Pitfall 4 | Low — duplicate display names are extremely rare; alternative (add `map_id` to breakdown) touches Phase-13 SDK surface |
| A3 | Litestar surfaces a `Literal` window mismatch as a 4xx (422); if a 400 is required, validate explicitly | Routes | Low — both are 4xx, satisfies SPEC; explicit guard available |
| A4 | Owner `user_id` is readily available at the flag/unflag emit sites (1307/1336) for `actor_user_id` | Event threading | Medium — verify; flag/unflag resolve by `message_id`/`verification_id`, owner id may need a fetch. Planner should confirm the lookup. |
| A5 | `bigserial` for `change_id` is house-acceptable (existing skill tables use `integer GENERATED ALWAYS AS IDENTITY`) | Migration | Low — both idiomatic; `bigserial` fits unbounded growth |

## Open Questions (RESOLVED)

1. **Does `PATCH /skill/tiers` need to capture history/change rows?** (A1)
   - What we know: D-09 lists it as a SYSTEM trigger; it runs `update_tier_config` → `compute_tier_boundaries` only, never `_do_recompute`, and changes no `skill_score`.
   - What's unclear: whether SYSTEM "global recalculation" rows should be written for a tier-percentile retune that moves no score.
   - Recommendation: Do NOT write rows for it (no score moved → no history). Flag at plan/discuss for a one-line confirm.
   - **RESOLVED: PATCH /skill/tiers runs `compute_tier_boundaries` only, moves no score → no capture path; leave `update_tier_config` untouched (no history/change rows written). Enforced in 14-04 Task 2.**

2. **Owner `user_id` availability at flag/unflag emit sites for `actor_user_id`.** (A4)
   - What we know: verify/moderate sites already have `completion_info["user_id"]` in scope; flag/unflag resolve by `message_id`/`verification_id`.
   - Recommendation: Planner verifies the owner id is fetchable at 1307/1336; if a lookup is needed, add it to `set_suspicious_flags`/`remove_suspicious_flags` before the emit.
   - **RESOLVED: flag/unflag lack the owner `user_id`; a completion-owner lookup (`fetch_completion_owner_by_message`) is added to `CompletionsRepository` in 14-03 (the completions domain owns `core.completions`) and called via `self._completions_repo` at the flag/unflag emit sites in 14-04 — no cross-service private-attribute access. Wired before the emit.**

## Project Constraints (from CLAUDE.md)
- Litestar DI module pattern; three-layer Controller → Service → Repository with `provide_*` DI.
- Raw asyncpg SQL, `$1,$2` positional params, CTEs; no ORM.
- Sequential numbered `.sql` migrations under `apps/api/migrations/`.
- msgspec `Struct` for all shared models; `*Request`/`*Response`/`*Event` suffixes; `UNSET`/`UnsetType` for PATCH optionals.
- BasedPyright strict; Ruff line-length 120; Google docstrings on public functions (not modules/classes/`__init__`).
- `log` (not `logger`); `%s` formatting; `log.exception` for caught errors.
- Repository methods take `*, conn: Connection | None = None` and use `self._get_connection(conn)`.
- Domain exceptions in `services/exceptions/skill.py`; controllers convert to `HTTPException`.
- `just lint-api` / `just lint-sdk` must be clean; tests via `just test-api`.
- All work goes through a GSD command (this is `/gsd:plan-phase` research).

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Reads are public (matches existing skill reads); no new auth |
| V3 Session Management | no | No sessions touched |
| V4 Access Control | yes | Drill-down ownership check: `WHERE change_id=$1 AND user_id=$2` → foreign id returns None → 404 (prevents enumerating another user's change detail by id) |
| V5 Input Validation | yes | msgspec strict decode for `window` Literal + `limit`/`offset` bounds (ge/le); positional SQL params (no interpolation) |
| V6 Cryptography | no | None |

| Threat Pattern | STRIDE | Standard Mitigation |
|----------------|--------|---------------------|
| SQL injection | Tampering | asyncpg `$1,$2` positional params (house rule); jsonb via codec, never string-built |
| IDOR on `/changes/{change_id}` | Information Disclosure | Ownership predicate `user_id=$2` in the lookup query → 404, not 403, to avoid confirming existence |
| Unbounded page size | DoS | `limit` capped `le=100` (tournaments convention) |
| Invalid window injection | Tampering | Literal-typed param rejected at decode |

## Sources

### Primary (HIGH confidence) — live source in this repo
- `apps/api/services/skill_service.py` — `_RecomputeGuard` (47), `recompute_all` (178), `_do_recompute` (201), `_player_breakdown` (130), scorer fns (77-127), `update_tier_config` transaction pattern (335)
- `apps/api/repository/skill_repository.py` — `replace_snapshot`/TRUNCATE (185/201), `fetch_snapshot` (168), `executemany` bulk pattern (204), `*, conn` convention
- `apps/api/events/schemas.py` — `SkillRecomputeRequestedEvent` (32)
- `apps/api/events/skill.py` — listener (15)
- `apps/api/services/completions_service.py` — `_emit_skill_recompute` (983) + 5 sites (1095/1097/1307/1336/1577)
- `apps/api/routes/v3/skill.py` — `SkillController` (23), auth opts
- `apps/api/routes/v3/tournaments.py` — limit/offset pagination (817)
- `apps/api/routes/v3/completions.py` — route threading of request+skill_service (204/255/275/382)
- `apps/api/migrations/0027_skill_score.sql`, `0028_skill_tier_config.sql` — DDL style, CHECK-not-enum
- `apps/api/app.py` — jsonb/numeric codec (200), nightly+cold-start poller (111)
- `apps/api/tests/conftest.py` — migration application (58), test_client/asyncpg_pool fixtures (114/93)
- `apps/api/tests/integration/test_skill.py` — `_recompute` driver (56), conservation assertion (448)
- `apps/api/tests/services/test_skill_service.py` — `_reset_guard` (51), burst-collapse test (101), mocked-repo pattern (43)
- `libs/sdk/src/genjishimada_sdk/skill.py` — struct/Literal conventions
- `.claude/skills/spike-findings-genjishimada/` SKILL.md + scoring-algorithm.md — `contribution` semantics, gamma decay

### Secondary / Tertiary
- None — no external research required; all findings verified in-repo.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all existing and exercised
- Architecture / control flow: HIGH — every line number verified against live source
- Pitfalls: HIGH — derived from the actual TRUNCATE ordering, guard collapse mechanics, and conservation proof
- Open questions A1/A4: flagged MEDIUM-LOW for plan-time confirmation

**Research date:** 2026-06-16
**Valid until:** 2026-07-16 (stable internal codebase; valid until Phase 13 surface changes)
