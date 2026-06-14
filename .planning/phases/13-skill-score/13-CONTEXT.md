# Phase 13: Skill Score - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

API-only vertical that adds a numeric **skill score** to Genji Parkour: a per-player
measure of in-game *performance* (clearing hard maps, fast relative to the field)
computed by the spike-validated hybrid scorer from verified non-legacy completions,
persisted to a `skill`-schema snapshot, surfaced as a sortable `skill_score` column on
the **existing community leaderboard** (not a separate board), and served via new
`/api/v3/skill/*` endpoints. Fully separate from XP (`lootbox.xp`) and from the existing
Ninja→God `skill_rank` label, both of which remain untouched. Bot slash commands and
website UI are explicitly later phases.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**9 requirements are locked.** See `13-SPEC.md` for full requirements, boundaries, and acceptance criteria.

Downstream agents MUST read `13-SPEC.md` before planning or implementing. Requirements are not duplicated here.

**In scope (from SPEC.md):**
- Migration `0027`: `skill` schema, snapshot table, weight config table seeded with adopted defaults
- `skill_repository` — input query (port of spike 001) and snapshot read/write
- `SkillService` — scoring algorithm (port of spike 002), reading weights from DB config
- SDK skill structs (request/response/summary/breakdown) in `libs/sdk/.../skill.py`
- `routes/v3/skill.py` — `GET /skill/users/{id}`, `GET /skill/users/{id}/breakdown`, `GET /skill/config`, `PATCH /skill/config`
- Community leaderboard integration — `skill_score` sortable column added to existing endpoint + `CommunityLeaderboardResponse`
- Snapshot freshness on verification change + symmetric removal (contract; mechanism chosen here — see decisions)

**Out of scope (from SPEC.md):**
- Discord bot slash commands for skill (`/skill`) — later phase; API-only here
- Website skill leaderboard UI and admin weight-tuning dashboard — later phase
- The existing XP system (`lootbox.xp`) and Ninja→God completion-rank tiers — untouched
- The existing `skill_rank` label on the community leaderboard — kept as-is alongside the new numeric column
- Medal-threshold backfill — uses existing `maps.medals` data as-is (bonus-only)
- A new auth scope for config — superuser/admin guard is reused, no new scope minted

</spec_lock>

<decisions>
## Implementation Decisions

These resolve the four HOW gray areas the SPEC left open. They do not change any SPEC requirement.

### Refresh trigger mechanism
- **D-01:** The snapshot recompute is triggered by a **Litestar in-process event** emitted
  *after* a verification state change commits — same pattern as the existing email/OCR
  background tasks. The verify/reject/flag HTTP response stays fast; the snapshot is fresh
  within ~90ms of the change. Chosen over a RabbitMQ consumer (the bot consumes events, not
  the API — awkward fit) and over inline synchronous recompute (would add ~90ms to every
  verify and couple verify success to recompute success).
- **D-02:** The in-process trigger MUST fire from **all** state-change paths, not just the
  happy-path verify:
  - `completions_service.verify_completion` (verify / un-verify)
  - the reject / `api.completion.verification.delete` path
  - `set_suspicious_flags` **and** `remove_suspicious_flags`
  These are the paths that change a row's eligibility (`verified`, `legacy` is immutable here,
  `suspicious_flags`). Missing any one breaks the symmetric add/remove acceptance criteria
  (SPEC req 8 & 9).
- **D-03:** A **nightly pg_cron full rebuild** is the durability backstop (pg_cron is already
  in the infra, used by the tournament cycle poller). It self-heals any snapshot lost to an
  API crash mid-recompute or any drift. The in-process event is the fast path; the cron is the
  floor. No manual admin rebuild endpoint was requested (can be added later if needed).

### Recompute scope
- **D-04:** Every trigger does a **full global recompute** (re-run the input query + scorer for
  all players, replace the whole snapshot). ~90ms / 261 players, SPEC-blessed. No dirty-map
  tracking, no partial-snapshot merge. The nightly cron uses the **same code path** — there is
  one rebuild routine, called by both the event and the cron.
- **D-05 (planner note, not a new decision):** Add a lightweight **"recompute already in flight,
  collapse" guard** so a burst of events (e.g. an admin clearing a verification queue) does not
  kick off N overlapping full rebuilds. A single in-flight flag / coalesce is sufficient; the
  user chose plain full-recompute, so this is a safety detail, not extra behavior.

### Breakdown & snapshot shape
- **D-06:** The per-map breakdown (`raw_score`, gamma-decayed `contribution`, badges:
  video / Gold|Silver|Bronze / WR) is stored as a **JSONB array on the snapshot row**, captured
  during recompute when the scorer already has every per-map score. `GET /skill/users/{id}/breakdown`
  is then a single cheap row fetch, always in sync with the score (same write). The app already
  has a `jsonb <-> msgspec` codec (`_async_pg_init`). Chosen over a separate breakdown table
  (~14,788 rows rewritten per recompute + transactional sync) and over on-demand compute (which,
  due to field-relativity, costs ~a full input query per read — `time_pct` needs the whole field).
- **D-07:** The snapshot table is **lean** — it holds only players with ≥1 eligible completion.
  Zero-score players (no eligible runs) are handled at read time: the community leaderboard
  **LEFT JOINs** the snapshot and **COALESCE(skill_score, 0)** (ranked last); `GET /skill/users/{id}`
  returns `0` with an empty breakdown when no row exists. Satisfies the empty-player acceptance
  criterion without writing rows for everyone.
- **D-08:** The leaderboard column / `CommunityLeaderboardResponse` field is named **`skill_score`**
  (SPEC draft confirmed; the `score_skill` typed during area selection was informal). It pairs with
  the existing untouched `skill_rank` label column.

### Config & PATCH semantics
- **D-09:** The weight config is a **single typed-column config row** seeded by migration `0027`
  with the adopted defaults: `diff_base=1.44, gamma=0.68, time_bonus=0.55, shrink_k=10.0,
  wr_bonus=0.10, partial_factor=0.60, medal_gold=1.12, medal_silver=1.07, medal_bronze=1.03`.
  One column per weight (the medal dict is flattened to `medal_gold/silver/bronze`), maps cleanly
  to a msgspec `Weights` struct, one SELECT. Chosen over key/value rows (untyped, runtime-surprise
  on a missing key). No scoring weight is a hardcoded literal in service/repository code.
- **D-10:** `PATCH /skill/config` (superuser-only, reusing the existing guard) updates the weights
  then **triggers an immediate full recompute** via the same rebuild routine as D-04. Scores reflect
  the new weights right away; the response can return the rebuilt state. Chosen over defer-to-cron
  (looks like nothing happened until the cron runs) and over a separate manual recompute step
  (easy to forget).

### Claude's Discretion
- Exact in-process event/struct name and listener registration (follow `apps/api/events/*.py`
  conventions and the `events/__init__.py` auto-discovery).
- Snapshot column types/names beyond the locked summary set (score, maps-cleared count,
  video-clear count, hardest raw difficulty, computed-at) and the JSONB breakdown column.
- The msgspec response/request struct field layouts for the four endpoints.
- Whether the "in-flight collapse" guard (D-05) is an asyncio lock, a boolean flag, or a DB
  advisory lock — implementer's call.
- Test-mode behavior: skill recompute is in-process (no RabbitMQ), so the `X-PYTEST-ENABLED=1`
  queue-skip does not gate it; ensure tests can trigger/assert a recompute deterministically.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements (read first)
- `.planning/phases/13-skill-score/13-SPEC.md` — Locked requirements, boundaries, constraints, and
  the 11 acceptance criteria. MUST read before planning.

### Spike findings (the locked algorithm & data layer)
- `Skill("spike-findings-genjishimada")` — project-local skill; auto-loads during skill-score work.
- `.claude/skills/spike-findings-genjishimada/references/skill-input-query.md` — the 4-CTE input
  query (`best → field → video_ranked → fully`), eligibility filters, `completion` flag = verification
  depth, `FILTER`-is-aggregate-only gotcha, never-compare-raw-time rule.
- `.claude/skills/spike-findings-genjishimada/references/scoring-algorithm.md` — the hybrid scorer
  (floor `diff_base ** (raw-1.5)`, video-gated proof multipliers, `Σ s_i / i**gamma`), gamma anti-farm
  dial, field-size shrink, adopted weights.
- `.claude/skills/spike-findings-genjishimada/sources/001-skill-input-query/query.py` — port source
  for the input query.
- `.claude/skills/spike-findings-genjishimada/sources/002-scoring-farming-resistance/score.py` — port
  source for `SkillService`.

### Existing code the phase integrates with
- `apps/api/repository/completions_repository.py` §60-189 — the real ranking SQL and the load-bearing
  `completion` flag semantics (also `migrations/0001_init.sql:482` COMMENT).
- `apps/api/services/completions_service.py` — `verify_completion` (~978), `verify_completion_with_pool`
  (~1068), the `api.completion.verification.delete` path (~725), `set_suspicious_flags` (~1209),
  `remove_suspicious_flags` (~1229): the trigger points for D-02.
- `apps/api/repository/community_repository.py` — `fetch_community_leaderboard` (the big CTE);
  `sort_column` Literal and `skill_rank` handling; the JOIN target for the new `skill_score` column.
- `libs/sdk/src/genjishimada_sdk/users.py:214` — `CommunityLeaderboardResponse` (gains `skill_score`).
- `apps/api/events/*.py` + `apps/api/events/__init__.py` — Litestar in-process event pattern (D-01).
- Tournament cycle transition (pg_cron + outbox poller, Phase 07) — precedent for the D-03 nightly
  rebuild; see `apps/api/migrations/0021_tournament_cycle_transitions.sql` and the outbox service.
- `apps/api/app.py` `_async_pg_init` — the `numeric→float` and `jsonb→msgspec` codecs (D-06 relies on
  the jsonb codec).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Litestar in-process event system** (`apps/api/events/`, auto-discovered) — the D-01 trigger
  mechanism; mirror the email/OCR background-task registration.
- **pg_cron + outbox poller** (tournament cycle transitions) — the D-03 nightly-rebuild precedent.
- **jsonb<->msgspec asyncpg codec** (`_async_pg_init`) — makes the D-06 JSONB breakdown column a
  typed read/write with no manual (de)serialization.
- **Superuser guard** (`middleware/guards.py` scope_guard; superusers bypass scope checks) — reused
  for `PATCH /skill/config`; no new scope minted (SPEC).
- **Three-layer Controller→Service→Repository** + `BaseService`/`BaseRepository` + `provide_*` DI —
  the shape for `routes/v3/skill.py`, `SkillService`, `skill_repository`.

### Established Patterns
- Raw asyncpg SQL, `$1,$2` params, CTEs, `DISTINCT ON`, `dict(row)` conversion — the input query port.
- Sequential numbered migrations; latest is `0026` → this phase is `0027`.
- One rebuild routine called by both the event trigger and the cron (D-04) — avoids divergent paths.
- `raw_difficulty::float8` (0–10 numeric), never the text tier; `time_pct` (field-relative), never raw
  time across maps — load-bearing scorer constraints (SPEC Constraints, spike refs).

### Integration Points
- **Trigger:** in-process event emitted from the verify / reject / suspicious-flag(±) service methods
  (D-02) → full-recompute routine (D-04) → snapshot upsert.
- **Leaderboard:** new `skill_score` field on `CommunityLeaderboardResponse`; `fetch_community_leaderboard`
  LEFT JOINs the snapshot, COALESCE(0), adds `skill_score` to the sortable `sort_column` Literal;
  `skill_rank` and all other columns unchanged (D-07, D-08).
- **Config:** `GET/PATCH /skill/config` read/write the single typed config row; PATCH → recompute (D-10).

</code_context>

<specifics>
## Specific Ideas

- User was explicit: `skill_score` is **an additional column on the existing community leaderboard**,
  alongside the other columns — **NOT a separate leaderboard**. (Confirms SPEC req 6.)
- Field name confirmed as `skill_score` (the `score_skill` form typed earlier was informal).
- Preference throughout for the **lowest-infra, codebase-native** option: in-process events over a new
  RabbitMQ consumer; reuse pg_cron rather than introduce new scheduling; JSONB-on-row over a second
  table.

</specifics>

<deferred>
## Deferred Ideas

- **Manual admin `POST /skill/recompute` endpoint** — not adopted (nightly cron + event chosen as the
  backstop). Cheap to add later if an operator wants on-demand recovery.
- **Discord `/skill` slash commands** and **website skill leaderboard UI / weight-tuning dashboard** —
  SPEC-deferred to later phases.
- **Weighting "video volume" more heavily** — the adopted weights accept that a prolific *video*
  player can rank below Hell-breadth grinders (spike-documented trade-off). Revisit only if the
  community wants it; tunable via `partial_factor`/`gamma` without code changes.

None of these are blockers for Phase 13.

</deferred>

---

*Phase: 13-skill-score*
*Context gathered: 2026-06-12*
