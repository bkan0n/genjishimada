# Phase 13: Skill Score - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 13-skill-score
**Areas discussed:** Refresh trigger mechanism, Recompute scope, Breakdown & snapshot shape, Config & PATCH semantics

> SPEC.md (9 requirements, ambiguity 0.134) locked the WHAT/WHY before this discussion.
> Only implementation (HOW) decisions were on the table.

---

## Area Selection

User selected all four offered areas and added an unprompted clarification:
> "This will be a column visible on the community leaderboard as score_skill in addition to the
> other columns there. NOT a separate leaderboard."

Captured as a confirmation of SPEC req 6 (column on the existing board, not a standalone leaderboard).
Field name later confirmed as `skill_score`.

---

## Refresh trigger mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Litestar in-process event | Emit event after verify/reject/flag commits; listener runs full recompute async (email/OCR pattern); no new infra; fresh within ~90ms; crash risk mitigated by a backstop | ✓ |
| Outbox + pg_cron poller | Reuse tournament pattern; durable, decoupled; eventually-consistent (poll-tick delay) | |
| Inline synchronous | Recompute inside the verify call before responding; simplest, strongest freshness; +90ms per verify, couples verify to recompute success | |

**User's choice:** Litestar in-process event.
**Notes:** Follow-up locked a **nightly pg_cron full rebuild** as the durability backstop (options were:
nightly cron ✓ / no backstop / manual admin endpoint). Trigger must fire from all state-change paths
(verify, reject/un-verify, suspicious-flag add+remove).

---

## Recompute scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full global recompute | Re-run input query + scorer for all players, replace whole snapshot; ~90ms; same path as cron | ✓ |
| Map-scoped recompute | Recompute only players on the affected map's field; smaller writes, more logic | |
| Full recompute, coalesced | Full recompute + debounce of event bursts | |

**User's choice:** Full global recompute.
**Notes:** Coalescing/in-flight-collapse retained as a planner safety note (D-05), not as adopted behavior.

---

## Breakdown & snapshot shape

| Option | Description | Selected |
|--------|-------------|----------|
| JSONB on the snapshot row | Breakdown array stored as JSONB, captured at recompute; cheap single-row read; existing jsonb codec | ✓ |
| Separate breakdown table | One row per (user,map); SQL-queryable; ~14,788 rows/rebuild + sync cost | |
| Compute on-demand | Re-run query+scorer at read; always fresh; ~full-input-query cost per read (field-relativity) | |

**User's choice:** JSONB on the snapshot row.

### Sub-question — Zero-score players

| Option | Description | Selected |
|--------|-------------|----------|
| LEFT JOIN + COALESCE to 0 | Lean snapshot (only ≥1 eligible run); leaderboard LEFT JOINs + COALESCE(0); endpoint returns 0/empty | ✓ |
| Materialize a 0-row per player | Write a row for all 261 players; plain INNER JOIN; larger writes | |

**User's choice:** LEFT JOIN + COALESCE to 0.

### Sub-question — Field name

| Option | Description | Selected |
|--------|-------------|----------|
| `skill_score` | Matches SPEC draft; pairs with `skill_rank` | ✓ |
| `score_skill` | Matches user's informal typing during area selection | |

**User's choice:** `skill_score`.

---

## Config & PATCH semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Single typed row | One row, typed column per weight (medal dict flattened); maps to msgspec Weights; SPEC-enumerated columns | ✓ |
| Key/value rows | One row per weight; flexible but untyped, runtime-surprise on missing key | |

**User's choice:** Single typed row.

### Sub-question — PATCH effect

| Option | Description | Selected |
|--------|-------------|----------|
| Immediate full recompute | PATCH writes weights then triggers the full-recompute path; scores reflect immediately | ✓ |
| Mark stale, defer to cron | PATCH only writes; next scheduled rebuild applies; looks like nothing happened | |
| PATCH writes; separate manual recompute | Two-step; explicit but forgettable | |

**User's choice:** Immediate full recompute.

---

## Claude's Discretion

- Event/struct naming and listener registration; snapshot column names/types beyond the locked set;
  endpoint struct field layouts; the concrete in-flight-collapse mechanism; deterministic test triggering
  of recompute (in-process, so not gated by `X-PYTEST-ENABLED`).

## Deferred Ideas

- Manual admin `POST /skill/recompute` endpoint (not adopted; cron+event chosen).
- Discord `/skill` slash commands and website skill UI / weight-tuning dashboard (SPEC-deferred).
- Weighting "video volume" more heavily (spike-documented trade-off; tunable via weights, no code change).
