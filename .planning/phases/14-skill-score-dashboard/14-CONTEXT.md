# Phase 14: Skill Score Dashboard - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

API-only vertical that adds a **forward-only history + per-change attribution layer**
riding the existing Phase 13 `recompute_all` routine, plus three read endpoints under
`/api/v3/skill/users/{id}/...`:
- `GET /history?window=7d|30d|90d|1y|all` — ordered score points + summary (best/lowest/average,
  first-vs-last point_change & percent_change).
- `GET /changes?window=…&limit=…` — newest-first paginated change feed (delta + cause_category).
- `GET /changes/{change_id}` — drill-down (prev/new/delta/percent, per-map `main_causes` top-N +
  `other_factors` summing to delta within 1e-6).

The Phase 13 scorer math, `weight_config`, and tier/percentile system are unchanged. The website
dashboard UI and any Discord bot surface are explicitly later phases.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**7 requirements are locked.** See `14-SPEC.md` for full requirements, boundaries, and acceptance criteria.

Downstream agents MUST read `14-SPEC.md` before planning or implementing. Requirements are not duplicated here.

**In scope (from SPEC.md):**
- A new migration adding timestamped per-user history + per-change capture (cause, prev/new/delta,
  before/after breakdown) in the `skill` schema.
- Wiring that capture into the existing single `recompute_all` routine (D-04 — no forked compute path).
- Threading a 3-category cause (`PLAYER_ACTION` / `MAP_ENVIRONMENT` / `SYSTEM`) through each recompute
  trigger, reusing the existing recompute `reason` channel.
- Three GET endpoints: `/skill/users/{id}/history` (+summary), `/skill/users/{id}/changes` (feed),
  `/skill/users/{id}/changes/{change_id}` (drill-down).
- Time-window filtering (7d/30d/90d/1y/all) on history and changes.
- New SDK msgspec structs for the responses; integration + service tests.

**Out of scope (from SPEC.md):**
- The website/frontend dashboard UI — separate later phase (no frontend codebase in this repo).
- A Discord bot surface for the dashboard — later phase.
- Backfill / reconstruction of pre-phase scores — unrecoverable; map difficulties/fields have drifted.
- Retention pruning, capping, or downsampling — unbounded forward-only for now.
- Push notifications / alerts on score change.
- Leaderboard-wide or multi-user history aggregation beyond the per-user endpoints.
- Any change to the Phase 13 scoring formula, `skill.weight_config`, or tier/percentile system.

</spec_lock>

<decisions>
## Implementation Decisions

These resolve the four HOW gray areas the SPEC left open (named in `14-SPEC.md` footer:
history table schema, capture wiring into `recompute_all`, pagination scheme, top-N cutoff).
They do not change any SPEC requirement.

### Storage shape
- **D-01:** **Two new tables** in the `skill` schema, not one combined table:
  - `skill.score_history` — lean time-series: `(user_id bigint, captured_at timestamptz, skill_score
    double precision)`, PK `(user_id, captured_at)`. This is all `/history` reads — fast, indexed, no
    heavy columns.
  - `skill.score_change` — rich per-change record: `change_id bigserial PK, user_id bigint, captured_at
    timestamptz, previous_score double precision, new_score double precision, delta double precision,
    cause_category text, reason text, diff jsonb`, with an index on `(user_id, captured_at DESC)` for the
    feed and a lookup path on `change_id` (+ ownership check on `user_id`). Chosen over one wide combined
    table so `/history` never carries the heavy `diff` column it doesn't need.
- **D-02:** Both tables get **one row per user-with-data on every recompute**, even when the user's score
  did not move (delta=0) — SPEC req 1 + Constraints (locked, not re-litigated). All rows produced by a
  single recompute share **one `captured_at`** (reuse the existing `computed_at = datetime.now(timezone.utc)`
  already minted at the top of `_do_recompute`).
- **D-03:** Retention is **unbounded, forward-only** (SPEC). No pruning/downsampling this phase.

### Drill-down diff storage
- **D-04:** `skill.score_change.diff` (jsonb) stores a **precomputed all-maps impact array**, NOT the raw
  before/after breakdowns:
  ```json
  { "maps": [ {"map": "<name>", "prev": <float>, "new": <float>, "impact": <new-prev>}, ... ] }
  ```
  `impact = new_contribution − prev_contribution` (decayed contribution, the `contribution` field the
  Phase 13 `_player_breakdown` already emits). A map present only before → `new=0`; a map present only
  after → `prev=0`. Gamma-decay rank shifts are captured automatically because each side uses its own
  snapshot's `contribution`. Therefore `Σ impact == delta` **exactly** at write time (conservation
  enforced at capture, no read-time recompute). Chosen over storing full prev+new breakdowns (~2× the
  breakdown JSONB per user per recompute) and over store-new-only-diff-at-read (fragile, breaks if a
  prior row is pruned).
- **D-05 (capture wiring):** `_do_recompute` MUST read the **previous snapshot's per-user score +
  breakdown before `replace_snapshot` TRUNCATEs**, so each user's `previous_score` and per-map `prev`
  contributions are available to build `score_history` + `score_change` rows. The diff is computed in
  the service (where the new breakdown is already in hand from `_player_breakdown`); the repository gets
  bulk-insert methods for the two new tables. This rides the **single `recompute_all` routine** (D-04
  from Phase 13) — no second compute path.
- **D-06:** **Store ALL per-map impacts; apply the top-N cut at READ time.** Because the cutoff is not
  baked into stored history, N stays tunable forever with no migration and no lost detail (forward-only
  history cannot be re-cut). Per-user map counts are small (<~50), so storing all impacts is cheap.

### Drill-down top-N cutoff (read-time)
- **D-07:** The `/changes/{change_id}` endpoint sorts `diff.maps` by **|impact| descending**, lists the
  **top 5 individually** as `main_causes` (`{map, reason, impact}`), and rolls the remaining tail into a
  single `other_factors` scalar. `N=5` is a **tunable code constant**, not a stored value. `sum(main_causes.impact)
  + other_factors == delta` within 1e-6 (the residual is exactly the tail because storage conservation is exact).

### Cause attribution
- **D-08:** **Per-user cause for a single clean completion trigger** (verify / un-verify / reject /
  flag / unflag / moderate of user X's run): the **actor X** (the completion owner) gets `PLAYER_ACTION`;
  **every other user-with-data** in that same global recompute gets `MAP_ENVIRONMENT` ("the competitive
  field around you changed"). This is what naturally populates `MAP_ENVIRONMENT`. Bystanders with delta=0
  still get a `MAP_ENVIRONMENT` row (one row per user per recompute is locked).
- **D-09:** **`SYSTEM` triggers** — `PATCH /skill/config`, `PATCH /skill/tiers`, the nightly pg_cron
  backstop, cold-start auto-fill, and **any coalesced burst** — tag **every** user-with-data `SYSTEM`
  with reason **"global recalculation"** (SPEC-locked).
- **D-10:** **Threading mechanism — structured event + guard accumulator.** Add typed fields to
  `SkillRecomputeRequestedEvent` (in `apps/api/events/schemas.py`): a `cause_category` and an
  `actor_user_id` (config/tier/nightly emit `SYSTEM` with `actor_user_id=None`). `recompute_all` accepts
  a trigger descriptor. The module-scope `_RecomputeGuard` **accumulates pending descriptors** during a
  burst (alongside its existing `rerun_requested` flag). Before `_do_recompute`, the holder decides:
  - **exactly ONE** completion descriptor with an `actor_user_id` → actor = `PLAYER_ACTION`,
    all other users = `MAP_ENVIRONMENT` (D-08).
  - **2+ accumulated descriptors OR any SYSTEM trigger present** → every user = `SYSTEM` "global
    recalculation" (D-09).
  Typed, no string-parsing of the `reason` suffix. The five `_emit_skill_recompute` call sites in
  `completions_service.py` must pass the completion owner's `user_id` as `actor_user_id`.

### Claude's Discretion
- **Pagination:** use `limit` + `offset` to match the codebase convention (`routes/v3/tournaments.py`
  uses `limit` ge=1 le=100 default 20, `offset` ge=0). Cursor pagination not required.
- Exact msgspec struct field layouts for the three response shapes (history+summary, change feed item,
  drill-down) in `libs/sdk/.../skill.py`; struct/field names beyond the locked semantic set.
- Exact column types/names beyond the D-01 sketch; index names; whether `cause_category` is a `text` +
  CHECK or a Postgres enum (lean toward a CHECK constraint or text + msgspec Literal, consistent with the
  codebase's avoidance of DB enums).
- The descriptor struct shape inside `_RecomputeGuard` and exact field names on the enriched event.
- Window→interval mapping for 7d/30d/90d/1y/all (relative to `now()`), and the summary anchoring math
  (already specified in SPEC req 3: anchor on earliest available record if the window predates it).
- Test-mode triggering: skill recompute is in-process (not RabbitMQ-gated by `X-PYTEST-ENABLED=1`);
  ensure tests can drive a recompute and assert history/change rows deterministically, including the
  coalesced-burst → SYSTEM path and the single-trigger → PLAYER/MAP path.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements (read first)
- `.planning/phases/14-skill-score-dashboard/14-SPEC.md` — Locked requirements (7), boundaries,
  constraints (scorer immutability, single recompute path, capture volume, cause threading,
  drill-down conservation), and acceptance criteria. MUST read before planning.

### Phase 13 decisions this phase rides on
- `.planning/phases/13-skill-score/13-CONTEXT.md` — D-04 (single global `recompute_all` routine),
  D-05 (`_RecomputeGuard` in-flight collapse), D-06 (JSONB breakdown via jsonb↔msgspec codec),
  D-07 (lean snapshot — only users-with-data get rows).
- `.planning/phases/13-skill-score/13-SPEC.md` — original skill-score requirements & constraints.

### Spike findings (locked algorithm & data layer — unchanged this phase, but read for `contribution`/breakdown semantics)
- `Skill("spike-findings-genjishimada")` — project-local skill; auto-loads during skill-score work.
- `.claude/skills/spike-findings-genjishimada/references/scoring-algorithm.md` — the hybrid scorer,
  gamma decay (`Σ sᵢ / iᵞ`) that defines the per-map `contribution` D-04 diffs.

### Existing code the phase integrates with
- `apps/api/services/skill_service.py` — `recompute_all` (~178), `_do_recompute` (~201, the capture
  wiring site for D-05), `_player_breakdown` (~130, source of per-map `contribution`),
  `_RecomputeGuard` (~47, the accumulator site for D-10). Scorer fns `_map_score`/`_player_score`
  are IMMUTABLE this phase.
- `apps/api/repository/skill_repository.py` — `replace_snapshot` (~185, TRUNCATE+rebuild; D-05 must
  read the old snapshot before this), `fetch_snapshot`/`fetch_weights`/`fetch_skill_inputs`; add the
  new history/change read + bulk-insert methods here.
- `apps/api/events/schemas.py:32` — `SkillRecomputeRequestedEvent` (gains `cause_category` +
  `actor_user_id`, D-10).
- `apps/api/events/skill.py:15` — the `@listener("skill.recompute.requested")` handler (passes the
  descriptor into `recompute_all`).
- `apps/api/services/completions_service.py` — `_emit_skill_recompute` (~984) and its five call sites
  (verify ~1095, un-verify ~1097, flag ~1307, unflag ~1336, moderate ~1577): thread the completion
  owner's `user_id` as `actor_user_id` (D-10).
- `apps/api/routes/v3/skill.py` — existing `/skill/*` controller; add the three new GET routes here.
- `apps/api/routes/v3/tournaments.py:817` — the `limit`/`offset` pagination convention to mirror.
- `libs/sdk/src/genjishimada_sdk/skill.py` — existing skill structs; add the new response structs.
- `apps/api/migrations/` — sequential numbering; latest is `0030` → this phase is `0031`.
- `apps/api/app.py` `_async_pg_init` — `jsonb→msgspec` and `numeric→float` codecs (D-04 `diff` jsonb
  relies on the jsonb codec).
- `apps/api/migrations/0027_skill_score.sql` — `skill.snapshot` shape (the source of `previous_score`
  + prev breakdown for D-05).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Single `recompute_all` + `_do_recompute` routine** (Phase 13 D-04) — the one place history/change
  capture is wired (SPEC: no forked compute path). The `computed_at` timestamp is already minted there.
- **`_RecomputeGuard`** (module-scope, Phase 13 D-05) — already coalesces bursts; extend it to also
  accumulate trigger descriptors so a coalesced burst → `SYSTEM` (D-10).
- **`_player_breakdown`** — already emits per-map `contribution`; the new breakdown is in hand during
  recompute, so the diff is a cheap prev-vs-new pass (D-04/D-05).
- **jsonb↔msgspec asyncpg codec** (`_async_pg_init`) — makes the `diff` jsonb column a typed read/write.
- **`limit`/`offset` pagination** (tournaments routes) — reuse for `/changes`.
- **Litestar in-process event + listener** (`events/skill.py`) — the trigger path to enrich with
  the structured cause/actor descriptor (D-10).

### Established Patterns
- Raw asyncpg SQL, `$1,$2` params, CTEs; sequential numbered migrations (next = `0031`).
- Three-layer Controller → Service → Repository + `provide_*` DI; `*Response`/`*Request` msgspec structs.
- Diff/conservation math lives in the service; bulk inserts live in the repository.
- `text` + msgspec `Literal` (not DB enums) is the codebase idiom for small closed sets like
  `cause_category` and the `window` parameter.

### Integration Points
- **Capture:** `_do_recompute` reads prev snapshot (score+breakdown) → builds per-user `score_history`
  + `score_change` rows → bulk-inserts both, riding the same routine as the event trigger, nightly
  backstop, and PATCH paths.
- **Cause:** enriched `SkillRecomputeRequestedEvent` + `_RecomputeGuard` accumulator decide per-user
  `cause_category`; `completions_service` call sites supply `actor_user_id`.
- **Read:** three new GET routes on the existing `/skill/*` controller → `SkillService` read methods →
  `skill_repository` queries on the two new tables (window filter, newest-first feed, change lookup
  with ownership check).

</code_context>

<specifics>
## Specific Ideas

- Preference (carried from Phase 13) for the **lowest-infra, codebase-native** option throughout:
  ride the single existing recompute routine, reuse the in-process event + `_RecomputeGuard`, JSONB
  payload over a third table, `limit`/`offset` over a new cursor scheme.
- The `diff` payload deliberately stores **all** map impacts (not pre-cut) so the top-N display rule
  stays a tunable read-time constant — the user values not freezing display choices into forward-only
  history.
- `MAP_ENVIRONMENT` is meant to read as "your score moved because the competitive field around you
  changed, not because of your own action" — the actor-vs-bystander split (D-08) is what gives that
  label real meaning.

</specifics>

<deferred>
## Deferred Ideas

- **Retention pruning / downsampling** of `score_history` and `score_change` — explicitly out of scope
  (unbounded forward-only for now, SPEC); revisit when volume warrants.
- **Website dashboard UI** (the screenshot) and a **Discord `/skill` history surface** — SPEC-deferred
  to later phases.
- **Cursor pagination** for the change feed — `limit`/`offset` is sufficient at current scale; upgrade
  later only if needed.
- **Manual admin recompute / on-demand recovery endpoint** — carried over as deferred from Phase 13.

None of these are blockers for Phase 14.

</deferred>

---

*Phase: 14-skill-score-dashboard*
*Context gathered: 2026-06-16*
