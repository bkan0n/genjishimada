# Phase 12: Overhaul of tournaments - Pattern Map

**Mapped:** 2026-06-01
**Files analyzed:** 9 (1 migration, 1 SDK, 1 repo, 2 services, 1 route, 1 bot ext, 2 test groups)
**Analogs found:** 9 / 9 (every file is a MODIFY of an existing file or a new file with a strong in-repo analog)

> This is a backend refactor of an already-shipped system (phases 01–11). Almost every file is
> MODIFIED in place. The work is *restructuring* (edition parent entity, one combined event) and
> *deleting the `now()` writes*, NOT building new machinery. Copy the existing skeletons verbatim
> and change only the specifics called out per file.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/migrations/0024_tournament_editions_overhaul.sql` | migration (schema + PL/pgSQL + pg_cron + data migration) | batch / event-driven (cron) | `0021_tournament_cycle_transitions.sql` + `0023_tournament_cycle_lifecycle_control.sql` + `0013_coin_store.sql` | exact (rewrites 0021/0023 fn; copies 0013 cron+lock skeleton) |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` (MODIFY) | model (msgspec structs) | transform / pub-sub payload | self — existing `TournamentCyclesStartedEvent`/`...CompletedEvent` (sdk:469–496) | exact (collapse 2 batch events → 1 combined; add edition structs) |
| `apps/api/repository/tournaments_repository.py` (MODIFY) | repository | CRUD | self — `create_active_cycle` (443–478), `fetch_config`/`update_config` (39–79), pause/debug setters (312–372) | exact |
| `apps/api/services/tournament_service.py` (MODIFY) | service | request-response + outbox write | self — `bootstrap_cycle` (341–432), `set_transitions_paused` (434–457), `set_debug_cycle_length` (459–485) | exact |
| `apps/api/services/tournament_outbox_service.py` (MODIFY) | service | pub-sub (outbox → RabbitMQ) | self — `publish_pending_transitions` (120–216), `_EVENT_ROUTING` (56–59), grouping (188–204) | exact |
| `apps/api/routes/v3/tournaments.py` (MODIFY) | route (Litestar Controller) | request-response | self — pause/debug-length/bootstrap handlers (464–590), config PATCH (91–112) | exact |
| `apps/bot/extensions/tournaments.py` (MODIFY) | bot consumer (discord.py CV2) | event-driven | self — `_on_cycle_started` (298–337) + `_on_cycle_completed` (339–410) + `_transfer_champion_role` (475–547) | exact (fuse the pair into one handler) |
| `apps/api/tests/repository/tournaments/test_edition_transitions.py` + `test_grid_boundary.py` (NEW) | test | event-driven (DB fn) | `tests/repository/tournaments/test_cycle_transitions.py`, `test_lifecycle_control.py`, `test_outbox_poller.py` | role-match (same test seam) |
| `apps/api/tests/{bot/test_tournaments_handler.py, integration/test_tournaments_schema.py, services/...}` (EXTEND) | test | event-driven / migration | existing same-named files | exact (extend in place) |

---

## Pattern Assignments

### `apps/api/migrations/0024_tournament_editions_overhaul.sql` (migration, batch/cron)

This single migration does six things. Each has a concrete in-repo analog. **Wrap DDL+DML in
`BEGIN;`/`COMMIT;` (like 0023), but keep the `CREATE EXTENSION` and `cron.schedule` blocks as
UNWRAPPED `DO $$ ... $$` guards (like 0021) so test DBs without pg_cron no-op.**

**(1) Edition table + child FK + config columns + drop per-category columns.** RESEARCH gives the
exact DDL (12-RESEARCH.md "Edition table" / "Global config columns" code blocks). Anchor for the
singleton-config + stored-timestamp shape is `0013_coin_store.sql:18–32` (the `store.config`
singleton with a real `next_rotation_at timestamptz` — the edition table is this shape generalized):
```sql
-- Analog: 0013_coin_store.sql:18-32
CREATE TABLE store.config (
    id                    int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    rotation_period_days  int NOT NULL DEFAULT 7 CHECK (rotation_period_days > 0),
    last_rotation_at      timestamptz NOT NULL DEFAULT now(),
    next_rotation_at      timestamptz NOT NULL DEFAULT now() + interval '7 days',
    ...
```
The `tournaments.config` columns to extend live at `0020_tournaments.sql:16` (config table) — add
`cadence`/`anchor_weekday`/`anchor_time`/`anchor_tz`/`transitions_paused`/`debug_cycle_seconds` via
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Per-category columns to DROP: `cycle_frequency`
(`0020:36–37`), and `transitions_paused`/`debug_cycle_seconds` (`0023:26–31`).

**(2) Grid-anchored transition function — REWRITE of `process_cycle_transitions()`.** Copy the
EXACT skeleton from `0023:43–220` (advisory lock + the tier-then-time RANK() snapshot CTE +
outbox INSERT) and change ONLY:
- The advisory lock line is verbatim — `0021:113` / `0023:60`:
```sql
-- Analog: 0023:60 (REUSE VERBATIM — do NOT collide with store lock 1234567890)
IF NOT pg_try_advisory_xact_lock(2025070100) THEN
    RAISE NOTICE 'Cycle transition already in progress, skipping';
    RETURN;
END IF;
```
- Detection: replace the per-category FOR loop (`0023:69–78`) with a single-edition check
  `WHERE edition.status='active' AND now() >= edition.ends_at`.
- **THE BUG TO DELETE:** `0023:151–153` and `0023:182–183` write `started_at = now()`. The rewrite
  NEVER writes `now()` into edition timestamps. The next edition inherits `started_at = old.ends_at`
  and `ends_at = old.ends_at + period` (RESEARCH Pattern 1, calc #1).
- The snapshot CTE is copied **verbatim** (`0023:88–122`) per child cycle — identical to
  `repository.fetch_leaderboard` (`tournaments_repository.py:1259–1279`). Do not re-derive.
- Outbox INSERT: replace the per-cycle `cycle_started`/`cycle_completed` INSERTs (`0023:131–141`,
  `159–203`) with ONE `edition_rollover` row carrying a combined `{results[], next[]}` payload.

**(3) `next_grid_boundary()` helper function — NEW PL/pgSQL.** RESEARCH Pattern 1 gives the full
body (12-RESEARCH.md:200–227). Follow the `CREATE OR REPLACE FUNCTION ... LANGUAGE plpgsql` +
`COMMENT ON FUNCTION` convention from `0021:33–89` (`select_eligible_map`). Used by bootstrap/resume
only — the only place `now()` is read (to pick a boundary, never to store one).

**(4) Map pre-roll reuse.** `select_eligible_map(p_category_id)` from `0021:33–86` is reused
**as-is** — the rewritten function still calls it per child cycle for the next edition.

**(5) Fresh-restart wipe + FK null (D-13/14/15).** RESEARCH "Fresh-restart wipe" block. The FK is
`ON DELETE SET NULL` already (`0020:170–172`); do the explicit NULL first for intent:
```sql
-- Analog: 0020_tournaments.sql:170-172 (the FK being NULLed)
ALTER TABLE core.completions
    ADD COLUMN IF NOT EXISTS tournament_completion_id int
    REFERENCES tournaments.completions(id) ON DELETE SET NULL;
-- Migration does:
UPDATE core.completions SET tournament_completion_id = NULL WHERE tournament_completion_id IS NOT NULL;
TRUNCATE tournaments.completions, tournaments.cycles, tournaments.editions RESTART IDENTITY CASCADE;
DELETE FROM tournaments.pending_transitions;
```
NEVER add CASCADE to that FK (Pitfall 4).

**(6) Idempotent pg_cron re-registration.** Copy `0021:274–291` VERBATIM. Keep the job NAME
`tournament-cycle-transitions` (A7); if the function is renamed, point the schedule at the new name:
```sql
-- Analog: 0021:274-291 (REUSE VERBATIM — guarded on pg_extension so test DBs no-op)
DO $body$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.unschedule('tournament-cycle-transitions') WHERE EXISTS (
            SELECT 1 FROM cron.job WHERE jobname = 'tournament-cycle-transitions'
        );
        PERFORM cron.schedule(
            'tournament-cycle-transitions', '* * * * *',
            'SELECT tournaments.process_edition_transitions()'
        );
    ELSE
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
    END IF;
END $body$;
```

---

### `libs/sdk/src/genjishimada_sdk/tournaments.py` (model, transform)

**Analog:** the existing batch event structs `TournamentCyclesStartedEvent` /
`TournamentCyclesCompletedEvent` (sdk:469–496) and their per-cycle elements (431–466).

**RETAIN** `TournamentCycleStartedEvent` (431–451) and `TournamentCycleCompletedEvent` (453–466) —
they become the per-category payload elements inside the new combined event (RESEARCH State of the
Art). **Add** `TournamentRolloverEvent` (collapses the two `Cycles*` batch structs) and the new
edition response struct(s). Pattern to copy (struct + Google docstring + `dt.datetime` fields):
```python
# Analog: sdk:469-496 (TournamentCyclesStartedEvent) — collapse the started/completed pair
class TournamentRolloverEvent(Struct):
    """One combined rollover: results of edition N (optional) + start of N+1 (optional)."""
    edition_id: int
    results: list[TournamentCycleCompletedEvent]   # empty on out-of-hiatus (start-only)
    started: list[TournamentCycleStartedEvent]      # empty on into-hiatus (results-only)
```
**Edition timing response** — mirror `TournamentCycleResponse` (221–240) but timing-owning:
```python
# Analog: sdk:221-240 (TournamentCycleResponse)
class TournamentEditionResponse(Struct):
    id: int
    started_at: dt.datetime
    ends_at: dt.datetime          # closes frontend-spec §8 (timing now stored, not derived)
    status: EditionStatus         # Literal['active','completed'] — mirror CycleStatus
    created_at: dt.datetime
```
The lifecycle-control structs move to global semantics: `TournamentCategoryLifecycleResponse`
(177–191), `TournamentPauseRequest` (194–202), `TournamentDebugCycleLengthRequest` (205–213) lose
their per-category `id` framing — reshape to config-level (drop `id` or rename to a config response).
**`*Request`/`*Response`/`*Event` suffix convention + `UNSET`/`UnsetType` for PATCH fields** (see
`TournamentConfigPatchRequest`-style structs and the `UNSET` usage at sdk:170–174). After editing:
run `just fix` (MEMORY.md — SDK is workspace-local; stale imports otherwise).

---

### `apps/api/repository/tournaments_repository.py` (repository, CRUD)

**Analog:** itself. Every new method copies an existing one verbatim and swaps the SQL.

**Edition CRUD** — copy `create_active_cycle` (443–478), but the INSERT takes computed grid
timestamps as `$n` params (NOT `now()` — that is the bug at line 469):
```python
# Analog: tournaments_repository.py:443-478 (create_active_cycle) — BUT the now() at line 469
# is the drift bug; the edition insert binds grid timestamps as parameters instead.
query = """
    INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
    VALUES ($1, $2, 'active', now())   -- ❌ THIS now() is the pattern to NOT copy for editions
    RETURNING *
"""
```
**Global config setters** — replace `set_category_paused` (312–341) and
`set_category_debug_cycle_seconds` (343–372) with config-level setters built on the existing
`update_config` allow-list builder (57–79) — note its SQL-injection-safe `SET field = $n` pattern
(field names from a fixed dict, values as positional params):
```python
# Analog: tournaments_repository.py:57-79 (update_config) — allow-list SET builder, no interpolation
for idx, (field, value) in enumerate(updates.items(), start=1):
    set_clauses.append(f"{field} = ${idx}")
    values.append(value)
query = f"UPDATE tournaments.config SET {', '.join(set_clauses)} WHERE id = 1"
```
**`fetch_config`** (39–55) `SELECT *` already returns the new columns automatically — no change
needed beyond consumers reading the new keys. **`fetch_leaderboard`** (1239–1281) is unchanged
(rewards stay per `cycle_id`, RESEARCH Pattern 4). **Outbox repo methods** (`create_pending_transition`
1340–1377, `fetch_unpublished_transitions` 1379–1408, `mark_transition_published` 1410–1434) stay —
`create_pending_transition` may need an `edition_id` param + nullable `cycle_id` (Pattern 3, A3).
**Every method:** `_conn = self._get_connection(conn)`, `conn: Connection | None = None` keyword-only,
catch `ForeignKeyViolationError`/`CheckViolationError` → `RepoFKError`/`CheckConstraintViolationError`
with `extract_constraint_name(e)` (see 436–441, 1369–1377).

---

### `apps/api/services/tournament_service.py` (service, request-response + outbox)

**Analog:** `bootstrap_cycle` (341–432), `set_transitions_paused` (434–457), `set_debug_cycle_length`
(459–485).

**`bootstrap_cycle` → `bootstrap_edition`:** keep the transaction shape (`async with
self._pool.acquire() as conn, conn.transaction():`, 365), the eligible-map + LRU-fallback selection
(384–398), and the outbox-write-in-same-txn pattern (425–430). **Change:** instead of
`create_active_cycle` (which stamps `started_at = now()`, 400–404, the bug per RESEARCH Pitfall 1),
compute the grid-snapped start via the new `next_grid_boundary()` and create the edition + child
cycles with that exact timestamp. The end-time computation at 406–414 (debug_seconds vs
weekly/biweekly) moves DB-side into the grid calc.

**`set_transitions_paused` / `set_debug_cycle_length` → global config setters:** keep the exact
method skeleton (repo call → `if row is None: raise ...NotFoundError` → `msgspec.convert(row,
Response)`). **PRESERVE the production guard** on the debug setter (480–481) — RESEARCH Security
Domain V4 requires it:
```python
# Analog: tournament_service.py:480-481 (KEEP — debug lever must reject in production)
if os.getenv("APP_ENVIRONMENT") == "production":
    raise DebugRouteDisabledError
```

---

### `apps/api/services/tournament_outbox_service.py` (service, pub-sub)

**Analog:** itself — `publish_pending_transitions` (120–216), `_EVENT_ROUTING` (56–59), `_build_event`
(92–117), the grouping accumulator (164–212).

**Collapse the routing maps** — one entry, one event type:
```python
# Analog: tournament_outbox_service.py:56-59 (_EVENT_ROUTING) — collapse to a single rollover route
_EVENT_ROUTING = {
    "edition_rollover": ("api.tournament.rollover", TournamentRolloverEvent),
}
```
**Replace `(event_type, created_at)` grouping (188) with `edition_id` grouping** — RESEARCH Pattern 3:
each `edition_rollover` row is already one combined event, so grouping mostly disappears; group by
`edition_id` if multiple rows can share a rollover, else one row → one publish. **Idempotency key**
changes from `tournament:{event_type}:{created_at_iso}` (203) to `tournament:rollover:{edition_id}`.
**PRESERVE:**
- The `FOR UPDATE SKIP LOCKED` + publish-before-mark at-least-once loop (166–206) verbatim.
- The reward side-effects called **once per child cycle** (per results entry) — `award_cycle_end`
  + `_reset_non_participant_streaks` (181–184) stay keyed on `cycle_id` (RESEARCH Pattern 4); now
  iterate `event.results` instead of one row.
- Deferred XP-grant publish AFTER commit (214–216) — `publish_xp_events` (CR-02 ordering).
- `msgspec.convert(row["payload"], struct_type)` round-trip (116) — keep payload keys byte-identical
  to the struct (Pitfall 5; a mismatch raises `ValidationError` and leaves the row unpublished).

---

### `apps/api/routes/v3/tournaments.py` (route, request-response)

**Analog:** the lifecycle handlers `set_transitions_paused` (511–547), `set_debug_cycle_length`
(549–590), `bootstrap_cycle` (464–510), and the config PATCH (91–112).

**Move pause/debug from `/categories/{id}/...` to config-level** (D-03 — global). Keep the Litestar
Controller conventions: `@litestar.patch(path=..., dependencies=..., opt={"required_scopes":
{"tournaments:write"}})`, service call inside a try/except that converts domain exceptions to
`HTTPException`/`CustomHTTPException`. The debug-length route keeps `tournaments:write` +
the service-side production guard. **Add edition reads** (Open Question 1 / A5): keep all per-cycle
endpoints (`/cycles/{id}/leaderboard` 671–676, `/cycles`, submit) cycle-scoped; surface edition
timing via a new `GET /editions/active` or by adding `edition_id` + edition `started_at`/`ends_at`
to the cycle response (closes frontend-spec §8). **Scope-guard opt pattern** is the cross-cutting
auth — see Shared Patterns.

---

### `apps/bot/extensions/tournaments.py` (bot consumer, event-driven)

**Analog:** `_on_cycle_started` (298–337) + `_on_cycle_completed` (339–410), fused via
`_transfer_champion_role` (475–547).

**Replace BOTH `@queue_consumer` handlers with ONE** `_on_edition_rollover` on
`api.tournament.rollover` / `TournamentRolloverEvent` / `idempotent=True`. The combined card uses
**conditional sections** (D-10) — copy the `ui.Container` + per-entry `ui.Separator()` +
`ui.TextDisplay(section)` build from BOTH existing handlers and gate each block on
`event.results` / `event.started`:
```python
# Analog: tournaments.py:339-410 (_on_cycle_completed) — ordering + CV2 + AllowedMentions to PRESERVE
# 1) champion transfers FIRST, only if there are results (Pitfall 5 ordering: roles before send)
categories = {}
for entry in event.results:
    category = await self.bot.api.get_tournament_category(entry.category_id)
    categories[entry.category_id] = category
    await self._transfer_champion_role(entry, category)   # REUSE 475-547 VERBATIM
# 2) ONE CV2 card: results Container section iff event.results, "new cycle" section iff event.started
```
**PRESERVE (load-bearing security/correctness rules):**
- Winners mentioned by numeric `<@id>` ONLY; `AllowedMentions(users=[Object(id=w)...],
  everyone=False, roles=False)` (405–408) — never from free-text names (T-10-10/T-11-19).
- `_transfer_champion_role` (475–547) reused unchanged — it strips ALL holders first (self-healing,
  so the first post-cutover rollover self-heals champion roles, A6) then grants the winner.
- The winners ping lives INSIDE a `ui.TextDisplay` in the LayoutView (CV2 `send` accepts no
  `content=`) — MEMORY.md "CV2 LayoutView no content" (394–400).
- Map/category data fetched via `self.bot.api.get_tournament_category` / `get_map` on receipt
  (bot never reads Postgres).

---

### Tests (NEW + EXTEND)

**Analogs:** `tests/repository/tournaments/test_cycle_transitions.py` (invokes the PL/pgSQL fn
directly — the model for `test_edition_transitions.py` and `test_grid_boundary.py`),
`test_lifecycle_control.py` (pause/debug behavior), `test_outbox_poller.py` (extend for the single
combined event), `tests/bot/test_tournaments_handler.py` (extend for the 3 conditional render cases),
`tests/integration/test_tournaments_schema.py` (extend for wipe/FK-null/bootstrap).

**Conventions** (MEMORY.md): targeted runs `uv run --directory apps/api pytest tests/<file>.py -p
no:xdist`; multi-file runs need `--no-testmon`; TRUE full suite `uv run --directory apps/api pytest
-n 4 --no-testmon` (testmon hides failures). pg_cron absent in test → invoke
`tournaments.process_edition_transitions()` directly (RESEARCH Environment Availability). Tests are
lint-exempt. Wave-0 gaps enumerated in 12-RESEARCH.md §"Wave 0 Gaps".

---

## Shared Patterns

### pg_cron + advisory-lock + idempotent reschedule (DB scheduled work)
**Source:** `apps/api/migrations/0013_coin_store.sql:280–300` (cron guard) + `0021:113–116`
(advisory lock) + `0021:274–291` (idempotent unschedule/schedule).
**Apply to:** the 0024 migration's transition function + cron registration.
**Rule:** lock id `2025070100` for tournaments (MUST NOT collide with store's `1234567890`); guard
`CREATE EXTENSION`/`cron.schedule` on `pg_extension` so test DBs no-op; `cron.unschedule(...) WHERE
EXISTS` before `cron.schedule(...)`.

### NEVER write `now()` into edition timestamps (the core fix)
**Source (anti-pattern):** `0023:151–153, 182–183` and `tournaments_repository.py:469`.
**Apply to:** migration transition fn, repo edition-create, service bootstrap.
**Rule:** edition `started_at`/`ends_at` come ONLY from `next_grid_boundary()` (bootstrap/resume) or
`prev.ends_at` (rollover). Grep the new migration + repo for `now()` near edition timestamp writes —
there must be none.

### Transactional outbox → RabbitMQ (publish-before-mark, at-least-once)
**Source:** `tournament_outbox_service.py:166–206` + `tournaments_repository.py:1379–1434`.
**Apply to:** the combined `edition_rollover` publish path.
**Rule:** `FOR UPDATE SKIP LOCKED` select → `publish_message(idempotency_key=...)` → mark published,
all in one txn; reward side-effects per child cycle inside the txn; non-idempotent XP notifications
deferred until after commit.

### Three-layer + DI (Controller → Service → Repository)
**Source:** `routes/v3/tournaments.py` Controller handlers + `tournament_service.py` +
`tournaments_repository.py`; `provide_tournament_repository` (repo:1437).
**Apply to:** all API changes. Routes thin; service holds business logic + outbox writes; repo holds
raw SQL with `self._get_connection(conn)` and `conn: Connection | None = None` keyword-only.

### Scope-guarded auth on routes
**Source:** `routes/v3/tournaments.py:96` (`opt={"required_scopes": {"tournaments:write"}}`),
`75`/`150` (`tournaments:read`).
**Apply to:** all new/moved tournament routes. Reads `tournaments:read`; mutations
`tournaments:write`; verification `tournaments:verify`. Debug-length also keeps the
`APP_ENVIRONMENT == 'production'` reject in the service.

### msgspec jsonb payload ↔ struct round-trip (Pitfall 5)
**Source:** `tournament_outbox_service.py:116` (`msgspec.convert(row["payload"], struct_type)`); the
SQL `jsonb_build_object` keys in `0023:135–140, 163–172`.
**Apply to:** the migration's `edition_rollover` payload build + the SDK `TournamentRolloverEvent`.
**Rule:** PL/pgSQL `jsonb_build_object` keys must be byte-identical to the struct field names; a
mismatch raises `msgspec.ValidationError` and (safely) leaves the row unpublished.

### CV2 announcement card + AllowedMentions safety
**Source:** `apps/bot/extensions/tournaments.py:375–408`.
**Apply to:** the combined rollover handler.
**Rule:** numeric-id-only winner mentions; `AllowedMentions(users=allow-list, everyone=False,
roles=False)`; ping text inside a `ui.TextDisplay` (LayoutView has no `content=`).

---

## No Analog Found

| File / Element | Role | Data Flow | Reason |
|----------------|------|-----------|--------|
| `tournaments.next_grid_boundary()` PL/pgSQL | utility (DB fn) | transform | No existing weekday/time/tz grid-boundary fn. **Closest structural analog:** the `CREATE OR REPLACE FUNCTION ... LANGUAGE plpgsql` + `COMMENT ON FUNCTION` convention of `0021:33–89` and the stored-`next_rotation_at` concept of `0013` `store.config`. The body is given verbatim in 12-RESEARCH.md Pattern 1 (lines 200–227) — DST handled via `AT TIME ZONE` + `EXTRACT(DOW)`. |

Everything else is a MODIFY of an existing file or a NEW file with an exact same-role analog.

---

## Metadata

**Analog search scope:** `apps/api/migrations/` (0013, 0020, 0021, 0022, 0023),
`apps/api/services/`, `apps/api/repository/`, `apps/api/routes/v3/`, `apps/api/app.py`,
`apps/bot/extensions/`, `libs/sdk/src/genjishimada_sdk/`, `apps/api/tests/`.
**Files scanned:** 9 source files read + table-structure greps of 0020.
**Pattern extraction date:** 2026-06-01
**Skills checked:** `.claude/skills/` + `.agents/skills/` are generic capability skills (no
project-specific rule overrides relevant to this mapping). Conventions sourced from CLAUDE.md +
MEMORY.md.
