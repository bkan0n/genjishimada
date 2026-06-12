# Phase 13: Skill Score - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 10 (6 new, 4 modified)
**Analogs found:** 10 / 10 (every file has a strong in-repo analog)

This is an API-only phase: Litestar + AsyncPG + msgspec, raw SQL, three-layer
Controller -> Service -> Repository. It ports two spike artifacts
(`sources/001-skill-input-query/query.py`, `sources/002-scoring-farming-resistance/score.py`)
into Genji's architecture and wires an in-process recompute event. Every new file
has a direct analog already in this codebase; the spike sources are the *algorithm*
to port, the analogs are the *shape* to port it into.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/migrations/0027_skill_score.sql` (NEW) | migration | schema/DDL | `migrations/0018_movement_techniques.sql` (schema+tables) + `0021_tournament_cycle_transitions.sql` (pg_cron) | exact (split: 0018 for DDL, 0021 for cron) |
| `apps/api/repository/skill_repository.py` (NEW) | repository | CRUD + analytic-read | `repository/completions_repository.py` §33-200 + `community_repository.py` (snapshot read/upsert ≈ `community` lean reads) | exact (role + multi-CTE windowed read) |
| `apps/api/services/skill_service.py` (NEW) | service | transform + CRUD | `services/community_service.py` (read+convert) + port of `sources/002.../score.py` | role-match (scorer is a port, not in-repo) |
| `apps/api/routes/v3/skill.py` (NEW) | controller/route | request-response | `routes/v3/community.py` (GET) + `routes/v3/content.py` (admin PUT/PATCH + nested namespace path) | exact |
| `libs/sdk/src/genjishimada_sdk/skill.py` (NEW) | model (SDK structs) | serialization | `routes/v3/content.py` response structs + `libs/sdk/.../users.py` `CommunityLeaderboardResponse` | exact |
| `apps/api/events/skill.py` (NEW) | event listener | event-driven | `events/completions.py` + `events/schemas.py` (the in-process listener + payload struct) | exact |
| `apps/api/repository/community_repository.py` (MOD) | repository | analytic-read | `fetch_community_leaderboard` itself (add LEFT JOIN + Literal member) | exact (in-place) |
| `libs/sdk/src/genjishimada_sdk/users.py` (MOD, ~line 214) | model | serialization | `CommunityLeaderboardResponse` itself (add one field) | exact (in-place) |
| `apps/api/services/completions_service.py` (MOD) | service | event-driven (emit) | `request.app.emit(...)` calls at §754 and §875 (D-02 trigger emit) | exact (in-place) |
| `apps/api/events/__init__.py` (MOD) | config (auto-discovery) | n/a | already auto-discovers; **no edit needed** — listener auto-registers | exact (no-op) |

**Note on `events/__init__.py`:** the context lists it as MODIFIED, but the registry
(`apps/api/events/__init__.py` §13-22) auto-discovers every `EventListener` in any
non-underscore module in `events/`. Dropping `events/skill.py` registers the listener
with **zero edits** to `__init__.py`. Planner: treat this as "no edit required" unless
the listener needs to live in an existing module.

---

## Pattern Assignments

### `apps/api/migrations/0027_skill_score.sql` (migration, schema/DDL)

Two analogs: **0018** for `CREATE SCHEMA` + table DDL style; **0021** for the optional
nightly pg_cron rebuild (D-03). Latest migration is `0026`, so this is `0027`.

**Schema + table DDL** — analog `migrations/0018_movement_techniques.sql:1-40`:
```sql
-- Migration: Add skill schema + snapshot + weight config
-- Date: 2026-06-12

BEGIN;

CREATE SCHEMA IF NOT EXISTS skill;

CREATE TABLE IF NOT EXISTS skill.<snapshot_table>
(
    user_id          bigint PRIMARY KEY,           -- lean: only players with >=1 eligible run (D-07)
    skill_score      double precision NOT NULL,
    maps_cleared     int NOT NULL,
    video_clears     int NOT NULL,
    hardest_raw      double precision NOT NULL,
    breakdown        jsonb NOT NULL DEFAULT '[]'::jsonb,  -- per-map array (D-06); jsonb codec exists
    computed_at      timestamptz NOT NULL DEFAULT now()
);
-- ... CREATE TABLE skill.<config_table> with one typed column per weight (D-09):
--     diff_base, gamma, time_bonus, shrink_k, wr_bonus, partial_factor,
--     medal_gold, medal_silver, medal_bronze (all double precision NOT NULL)
-- ... INSERT the single seeded config row with the adopted defaults (D-09).

COMMIT;
```
Conventions confirmed in 0018: `BEGIN; ... COMMIT;`, `IF NOT EXISTS`, `int GENERATED
ALWAYS AS IDENTITY PRIMARY KEY`, `timestamptz NOT NULL DEFAULT now()`. Seed the config
row with the locked D-09 defaults (`diff_base=1.44, gamma=0.68, time_bonus=0.55,
shrink_k=10.0, wr_bonus=0.10, partial_factor=0.60, medal_gold=1.12, medal_silver=1.07,
medal_bronze=1.03`).

**Optional nightly pg_cron rebuild (D-03)** — analog `migrations/0021_...sql:14-20` (guarded
extension) and `:274-291` (idempotent registration). Both blocks are **guarded so test/local
DBs without pg_cron no-op**, which keeps Acceptance criterion "0027 applies cleanly on a
fresh test DB" true:
```sql
DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
END $$;

DO $body$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.unschedule('skill-nightly-rebuild') WHERE EXISTS (
            SELECT 1 FROM cron.job WHERE jobname = 'skill-nightly-rebuild');
        PERFORM cron.schedule('skill-nightly-rebuild', '0 4 * * *', 'SELECT ...');
    ELSE
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
    END IF;
END $body$;
```
**Caveat (planner decision):** the cron must invoke the *same* rebuild routine the event
uses (D-04). The Python rebuild lives in `SkillService`, not SQL — so the cron either calls
a thin SQL stored proc that reproduces the scorer (heavy duplication, see the 0021
"DUPLICATION NOTE" §29-32 rationale) **or** the D-03 backstop is implemented as an
app-side scheduled task rather than pg_cron. Flag this for the planner: the 0021 cron
precedent applies *only if* the rebuild can be expressed in SQL; otherwise prefer an
app-side scheduler and the cron block is omitted.

---

### `apps/api/repository/skill_repository.py` (repository, multi-CTE read + snapshot upsert)

**Analog:** `apps/api/repository/completions_repository.py` (class shape, multi-CTE windowed
SQL, `DISTINCT ON`, `dict(row)` conversion) and `community_repository.py:720-722` (provide fn).
The **input query is a port of `sources/001-skill-input-query/query.py:24-92`** — that exact
4-CTE SQL (`best -> field -> video_ranked -> fully`) drops verbatim into a repository method;
only the runner harness (asyncpg.connect / JSON dump) is discarded.

**Class + provider skeleton** — analog `completions_repository.py:22-31` + `:2058`:
```python
from __future__ import annotations
from asyncpg import Connection, Pool
from litestar.datastructures import State
from repository.base import BaseRepository

class SkillRepository(BaseRepository):
    def __init__(self, pool: Pool) -> None:
        super().__init__(pool)

# at module bottom (mirrors community_repository.py:720):
async def provide_skill_repository(state: State) -> SkillRepository:
    """Litestar DI provider for SkillRepository."""
    return SkillRepository(state.db_pool)
```

**Input-query method** — port `sources/001.../query.py:24-92` into a repo method; wrap with
the `BaseRepository` connection pattern (`completions_repository.py:54`):
```python
async def fetch_skill_inputs(self, *, conn: Connection | None = None) -> list[dict]:
    _conn = self._get_connection(conn)
    rows = await _conn.fetch(SKILL_INPUT_QUERY)   # the verbatim 4-CTE port
    return [dict(r) for r in rows]
```
The ported `SKILL_INPUT_QUERY` keeps every signal column the scorer needs:
`raw_difficulty::float8`, `time::float8`, `fully_verified` (`completion = FALSE`),
`field_size`, `field_rank`, `video_rank`, `time_pct` (1.0 = fastest), computed `medal`,
`has_medal_thresholds`, `suspicious`. **Load-bearing gotchas carried from the spike:**
- `completion = TRUE` -> partial (screenshot); `completion = FALSE` -> full (video). Proof
  multipliers apply ONLY to `completion = FALSE`. (Confirmed `migrations/0001_init.sql:482`
  COMMENT + `completions_repository.py:60-189`.)
- `rank() OVER (...) FILTER (...)` is INVALID in Postgres — the spike ranks the video set
  in its own `video_ranked` CTE and `LEFT JOIN`s it back. Do not collapse it.
- Eligibility filter (also SPEC req 3): `c.verified = TRUE AND c.legacy = FALSE AND
  m.archived = FALSE AND m.code IS NOT NULL`; suspicious-flagged rows dropped (the
  `suspicious` EXISTS column, filtered in the scorer/repo).
- Never compare raw `time` across maps — always `time_pct`.

**Snapshot read** (single cheap row; the `breakdown` jsonb decodes via the app codec, D-06):
```python
async def fetch_snapshot(self, user_id: int, *, conn: Connection | None = None) -> dict | None:
    _conn = self._get_connection(conn)
    row = await _conn.fetchrow("SELECT * FROM skill.<snapshot> WHERE user_id = $1", user_id)
    return dict(row) if row else None
```

**Snapshot bulk upsert** (the recompute replaces the whole lean snapshot, D-04/D-07). Model
on the `$1,$2` positional convention and CTE style; a `TRUNCATE`+`INSERT ... SELECT
unnest(...)` or `executemany`/`copy_records_to_table` inside one transaction is the natural
shape. The `breakdown` column is written as a Python list; the `_jsonb_encoder`
(`app.py:132`) serializes it automatically.

**Config read/write** (single typed row, D-09):
```python
async def fetch_weights(self, *, conn=None) -> dict: ...          # SELECT * FROM skill.<config> LIMIT 1
async def update_weights(self, weights: dict, *, conn=None): ...  # UPDATE skill.<config> SET diff_base=$1, ...
```

---

### `apps/api/services/skill_service.py` (service, transform + CRUD)

**Analog:** `services/community_service.py` (full service shape: `BaseService` subclass,
repo injected, `msgspec.convert(rows, list[...])`, `provide_*` at bottom). The **scoring
math is a faithful port of `sources/002-scoring-farming-resistance/score.py:44-89`** —
`diff_weight`, `map_score`, `player_score`, `player_breakdown`. The dataclass `Weights`
becomes a msgspec `Weights` struct loaded from the DB config (D-05/req 5: NO hardcoded
weights — read `fetch_weights()` at compute time).

**Service skeleton + provider** — analog `community_service.py:27-39` + `:123-128`:
```python
class SkillService(BaseService):
    def __init__(self, pool: Pool, state: State, skill_repo: SkillRepository) -> None:
        super().__init__(pool, state)
        self._skill_repo = skill_repo

async def provide_skill_service(state: State, skill_repo: SkillRepository) -> SkillService:
    """Litestar DI provider for SkillService."""
    return SkillService(state.db_pool, state, skill_repo)
```

**Ported scorer** (from `score.py:44-67`; weights come from DB, not literals):
```python
def _diff_weight(raw: float, w: Weights) -> float:
    return w.diff_base ** (raw - 1.5)

def _map_score(row: dict, w: Weights) -> float:
    floor = _diff_weight(row["raw_difficulty"], w)
    if not row["fully_verified"]:
        return floor * w.partial_factor                  # partial: floor only
    field_size = row["field_size"] or 1
    shrink   = field_size / (field_size + w.shrink_k)    # field-size shrink REQUIRED (constraint)
    time_mult  = 1 + w.time_bonus * shrink * (row["time_pct"] or 0.0)
    medal_mult = {"Gold": w.medal_gold, "Silver": w.medal_silver,
                  "Bronze": w.medal_bronze}.get(row["medal"], 1.0) if row["medal"] else 1.0
    wr_mult    = 1 + w.wr_bonus if row["video_rank"] == 1 else 1.0
    return floor * time_mult * medal_mult * wr_mult

def _player_score(rows: list[dict], w: Weights) -> float:
    scores = sorted((_map_score(r, w) for r in rows), reverse=True)
    return sum(s / (i ** w.gamma) for i, s in enumerate(scores, start=1))   # gamma >= 0.5 always
```
`player_breakdown` (port of `score.py:70-89`) produces the per-map JSONB array
(`raw_score`, gamma-decayed `contribution`, badges video/medal/WR) captured during
recompute and stored on the snapshot row (D-06).

**The one rebuild routine** (D-04, called by event AND the D-03 backstop AND PATCH D-10):
```python
async def recompute_all(self) -> None:
    weights = await self._skill_repo.fetch_weights()      # no hardcoded weights (req 5)
    rows = await self._skill_repo.fetch_skill_inputs()    # the 4-CTE port
    # group by user_id (score.py:92-106 score_all), score + breakdown each, upsert snapshot
```
Add the D-05 "in-flight collapse" guard (asyncio.Lock / boolean flag — implementer's call)
so a burst of verify events does not launch N overlapping full rebuilds.

**Read methods** mirror `community_service.py` (`msgspec.convert`), with the D-07 empty-player
rule: `get_user_skill(id)` returns score `0` + empty breakdown when no snapshot row exists.

---

### `apps/api/routes/v3/skill.py` (controller, request-response)

**Analog:** `routes/v3/community.py` (GET handlers, `Controller` with class-level `path`/
`tags`/`dependencies`, `Provide(provide_*)`) and `routes/v3/content.py` for the **admin-write
pattern + nested namespace path** (`path = "/content/movement-tech"`).

**Controller skeleton** — analog `community.py:26-34`:
```python
class SkillController(Controller):
    path = "/skill"
    tags = ["Skill"]
    dependencies = {
        "skill_repo": Provide(provide_skill_repository),
        "skill_service": Provide(provide_skill_service),
    }
```
The registry (`routes/v3/__init__.py:13-24`) auto-collects any `Controller` in the module —
**no manual registration**; just create the file.

**GET handlers** — analog `community.py:36-64` (path, summary, description, typed return,
service call). Four endpoints (SPEC req 7):
- `GET /skill/users/{id}` -> total + summary
- `GET /skill/users/{id}/breakdown` -> per-map rows (single snapshot fetch, D-06)
- `GET /skill/config` -> current weights

**PATCH /skill/config — superuser-only** (D-10, reuses the existing guard; NO new scope).
The superuser path in `middleware/guards.py:24-25` (`if auth.is_superuser: return`) means a
superuser passes any guarded route, while a non-superuser with no matching `required_scopes`
is rejected 401. So declaring an `opt={"required_scopes": {...}}` that no normal token holds
(or simply a non-excluded route with required_scopes a regular user lacks) yields
superuser-only. Model the write handler on `content.py:282-321` (`@put`/admin write with
`opt={"required_scopes": {...}}`):
```python
@patch(path="/config", summary="Update Skill Weights",
       opt={"required_scopes": {"skill:admin"}})   # superuser bypasses; others 401/403
async def update_config(self, skill_service: SkillService, data: SkillConfigUpdateRequest):
    weights = await skill_service.update_weights(data)
    await skill_service.recompute_all()              # D-10: immediate full recompute
    return weights
```
(Guard reference: `middleware/guards.py` `scope_guard` — superuser bypass at the top, scope
check otherwise. The SPEC says "no new scope minted"; if a sentinel scope feels wrong, an
inline `if not request.user.is_superuser: raise NotAuthorizedException` in the handler is the
alternative — planner's call, both satisfy req 7's 401/403-for-non-superuser criterion.)

---

### `libs/sdk/src/genjishimada_sdk/skill.py` (SDK structs, serialization)

**Analog:** `routes/v3/content.py:108-172` (msgspec `Struct` response shapes, `frozen=True`)
and `libs/sdk/.../users.py:214-245` `CommunityLeaderboardResponse` (response struct with
docstring `Attributes:` block). Per Conventions: `*Request` / `*Response` suffixes; `str |
None` unions; `msgspec.UNSET` / `UnsetType` for optional PATCH fields.

**Struct shapes** — analog `users.py:214-245` + `content.py:99-100` (UNSET for PATCH):
```python
import msgspec
from msgspec import Struct, UNSET, UnsetType

class Weights(Struct):                 # maps 1:1 to the D-09 config row
    diff_base: float
    gamma: float
    time_bonus: float
    shrink_k: float
    wr_bonus: float
    partial_factor: float
    medal_gold: float
    medal_silver: float
    medal_bronze: float

class SkillConfigUpdateRequest(Struct):    # PATCH: all fields optional (content.py:99 UNSET pattern)
    diff_base: float | UnsetType = UNSET
    gamma: float | UnsetType = UNSET
    # ... one optional field per weight

class SkillSummaryResponse(Struct):        # GET /skill/users/{id}
    user_id: int
    skill_score: float
    maps_cleared: int
    video_clears: int
    hardest_raw: float

class SkillBreakdownRow(Struct):           # one per-map breakdown entry (D-06 jsonb element)
    map_name: str
    raw: float
    fully_verified: bool
    medal: str | None
    wr: bool
    raw_score: float
    contribution: float
    rank: int
```
The breakdown row mirrors the spike's `player_breakdown` dict keys
(`score.py:78-88`). The jsonb<->msgspec codec (`app.py:127-128`) decodes the stored array
straight into `list[SkillBreakdownRow]`.

---

### `apps/api/events/skill.py` (event listener, event-driven) + recompute trigger

**Analog:** `events/completions.py:17-40` (the `@listener(...)` async handler with DI-injected
services) and `events/schemas.py:6-13` (the msgspec event payload struct). This is the D-01
in-process trigger — same mechanism as the OCR/email background tasks.

**Event payload** — analog `events/schemas.py:6-13`:
```python
# in events/schemas.py (or events/skill.py)
import msgspec

class SkillRecomputeRequestedEvent(msgspec.Struct):
    """Emitted after a verification-state change commits (D-01/D-02)."""
    # full recompute (D-04) carries no map_id; can be empty or carry a reason for logs
```

**Listener** — analog `events/completions.py:17-40`:
```python
import logging
from litestar.events import listener
from events.schemas import SkillRecomputeRequestedEvent
from services.skill_service import SkillService

log = logging.getLogger(__name__)

@listener("skill.recompute.requested")
async def handle_skill_recompute(event: SkillRecomputeRequestedEvent, skill_service: SkillService) -> None:
    """Recompute the whole skill snapshot in the background (D-04)."""
    await skill_service.recompute_all()
```
**Registration:** automatic. `events/__init__.py:13-22` discovers every `EventListener` in
non-underscore modules — dropping `events/skill.py` registers `handle_skill_recompute` with
no `__init__.py` edit. **Test-mode caveat (D-05 / CONTEXT discretion):** this is in-process,
NOT a RabbitMQ publish, so the `X-PYTEST-ENABLED=1` queue-skip does NOT gate it; tests can
emit the event and assert a recompute deterministically.

---

### `apps/api/repository/community_repository.py` (MOD — leaderboard skill_score column)

**Analog:** the existing `fetch_community_leaderboard` (`community_repository.py:17-232`),
edited in place. Three surgical changes (D-07, D-08):

1. **Add to the `sort_column` Literal** (`:22-31`) — add `"skill_score"`:
```python
sort_column: Literal[
    "xp_amount", "nickname", "prestige_level", "wr_count", "map_count",
    "playtest_count", "discord_tag", "skill_rank", "skill_score",
] = "xp_amount",
```
2. **LEFT JOIN the snapshot + COALESCE(0)** — the leaderboard is built from CTEs ending in a
final SELECT (`:204-228`). Add a CTE / LEFT JOIN to `skill.<snapshot>` and select
`coalesce(ss.skill_score, 0) AS skill_score` (D-07: zero-score players ranked last). The
join goes alongside the existing `LEFT JOIN world_records wr`, `LEFT JOIN map_counts mc`
block (`:219-222`):
```sql
        LEFT JOIN skill.<snapshot> ss ON u.id = ss.user_id
...
        coalesce(ss.skill_score, 0) AS skill_score,
```
3. **`sort_values` mapping** — `skill_score` sorts as a plain numeric column (like `xp_amount`),
so the `else: sort_values = sort_column` branch (`:75-76`) already handles it; no special CASE
needed (unlike `skill_rank` at `:63-74`).

**Mirror in `community_service.py` and `routes/v3/community.py`:** the `sort_column` Literal is
duplicated in all three (`community_service.py:46-55`, `community.py:51-60`). Add `"skill_score"`
to each. The `skill_rank` label column is UNTOUCHED (SPEC req 6).

---

### `libs/sdk/src/genjishimada_sdk/users.py` (MOD ~line 214 — add skill_score field)

**Analog:** `CommunityLeaderboardResponse` itself (`users.py:214-245`), one field added:
```python
class CommunityLeaderboardResponse(Struct):
    ...
    skill_rank: str          # UNCHANGED — the Ninja->God label (SPEC: must remain)
    skill_score: float       # NEW — numeric skill score (D-08); coalesced to 0 in SQL
    total_results: int
```
`skill_score` is non-optional `float` because the SQL `COALESCE(..., 0)` guarantees a value
for every row (D-07). Field name is `skill_score` (D-08 confirmed; the informal `score_skill`
is wrong).

---

### `apps/api/services/completions_service.py` (MOD — emit recompute from all D-02 paths)

**Analog:** the existing `request.app.emit(...)` calls at `completions_service.py:754-766`
and `:875-888` — the exact in-process emit shape to copy. The recompute event must fire from
**all four** state-change paths (D-02; missing one breaks SPEC req 8/9 symmetry):

| Path | Location | Notes |
|------|----------|-------|
| `verify_completion` (verify / un-verify) | `:978-1066` (emit AFTER the verify commits, near the `:1053` event publish) | both `data.verified = True` and `False` must emit |
| reject / `api.completion.verification.delete` | `:723-730` | the verification-delete branch |
| `set_suspicious_flags` | `:1209-1227` | flagging drops a user's contribution |
| `remove_suspicious_flags` | `:1229-1238` | un-flagging restores it |

**Emit pattern** — copy from `:754`:
```python
request.app.emit(
    "skill.recompute.requested",
    SkillRecomputeRequestedEvent(),
    skill_service=skill_service,   # DI-injected listener arg, like svc=/users=/notifications= at :763-765
)
```
**Caveats for the planner:**
- `verify_completion` already has `request` (may be `None` for event-driven calls — `:980`
  `request: Request | None`; guard the emit with `if request is not None`).
- `set_suspicious_flags` / `remove_suspicious_flags` currently take **no `request`** (`:1209`,
  `:1229`). To emit, either thread `request`/`app` through (the controller has it — see
  `completions.py` handlers with `request: Request`) or have those service methods accept an
  `app`/`request` param. The route-side `CompletionsController.dependencies`
  (`completions.py:61-71`) is where a `provide_skill_service` would be added so the recompute
  listener's `skill_service` arg resolves.
- Emit only AFTER the DB state change commits (D-01: the HTTP response stays fast; recompute
  runs in background). The existing emits at `:754`/`:875` are likewise post-commit.

---

## Shared Patterns

### Three-layer DI wiring (Controller -> Service -> Repository)
**Source:** `community_service.py:123-128`, `community_repository.py:720-722`,
`community.py:31-34`.
**Apply to:** `skill_repository.py`, `skill_service.py`, `routes/v3/skill.py`.
Each layer ends with an `async def provide_<thing>(state: State, ...) -> <Thing>` that the
controller wires via `dependencies = {"name": Provide(provide_...)}`. Repos take
`state.db_pool`; services take `(state.db_pool, state, <repo>)`.

### Raw-SQL repository conventions
**Source:** `completions_repository.py:54` (`_conn = self._get_connection(conn)`),
`base.py:23-32`, `community_repository.py:231-232` (`[dict(row) for row in rows]`).
**Apply to:** every `skill_repository.py` method. `$1,$2` positional params, multi-line
triple-quoted SQL, CTEs, `DISTINCT ON`, `fetchrow`/`fetch`/`fetchval`, `dict(row)` conversion,
optional `conn: Connection | None = None` keyword-only param.

### msgspec convert at the service boundary
**Source:** `community_service.py:61-70` (`msgspec.convert(rows, list[...Response])`).
**Apply to:** all `skill_service.py` read methods returning SDK structs.

### jsonb <-> msgspec codec (free serialization)
**Source:** `app.py:125-139` (`_async_pg_init` sets `jsonb` + `numeric` codecs).
**Apply to:** the D-06 `breakdown` JSONB column — write a Python list, read back a decoded
list; `numeric` columns auto-decode to `float` (so `raw_difficulty::float8` casts are belt-
and-suspenders). No manual (de)serialization needed.

### In-process event (emit + listener + auto-registration)
**Source:** emit `completions_service.py:754`; listener `events/completions.py:17`; payload
`events/schemas.py:6`; auto-discovery `events/__init__.py:13-22`.
**Apply to:** the D-01/D-02 recompute trigger. Emit is fire-and-forget post-commit; the
listener gets services via DI; no `__init__.py` edit needed.

### Superuser-only write guard (no new scope)
**Source:** `middleware/guards.py` `scope_guard` (`if auth.is_superuser: return` at top);
admin-write opt `content.py:282-286` (`opt={"required_scopes": {...}}`).
**Apply to:** `PATCH /skill/config`. Superusers bypass; non-superusers without the scope get
401/403 (SPEC req 7). SPEC says reuse the guard, mint no new scope.

### Sequential numbered migration with guarded pg_cron
**Source:** DDL `0018_movement_techniques.sql:1-40`; guarded cron `0021_...sql:14-20` & `274-291`.
**Apply to:** `0027_skill_score.sql`. `BEGIN;...COMMIT;`, `CREATE SCHEMA IF NOT EXISTS`,
`IF NOT EXISTS` tables, seed the config row; wrap any pg_cron in the `pg_extension`-guarded
`DO` block so fresh test DBs no-op (keeps "applies cleanly on a fresh test DB" true).

---

## No Analog Found

None. Every file maps to an in-repo analog. The only "not in repo" pieces are the **scoring
math** and the **input SQL**, which are explicit ports of the two spike source files
(`sources/001-skill-input-query/query.py`, `sources/002-scoring-farming-resistance/score.py`)
and are not expected to exist in the codebase yet.

---

## Metadata

**Analog search scope:** `apps/api/{migrations,repository,services,routes/v3,events,middleware}`,
`libs/sdk/src/genjishimada_sdk/`, `apps/api/app.py`,
`.claude/skills/spike-findings-genjishimada/{references,sources}`.
**Files scanned (read):** 18.
**Spike ports identified:** input query (001), scorer (002).
**Pattern extraction date:** 2026-06-12.
