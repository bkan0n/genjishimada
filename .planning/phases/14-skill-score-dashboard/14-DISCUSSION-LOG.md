# Phase 14: Skill Score Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-16
**Phase:** 14-skill-score-dashboard
**Areas discussed:** Storage shape, Drill-down diff storage, Top-N cutoff, Cause attribution

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Storage shape | History + change table layout | ✓ |
| Drill-down diff storage | What before/after data to persist for the drill-down | ✓ |
| Cause attribution | trigger→cause flow + per-user PLAYER/MAP/SYSTEM semantics | ✓ |
| Top-N cutoff | main_causes vs other_factors split | ✓ |

**User's choice:** All four areas.

---

## Storage shape

| Option | Description | Selected |
|--------|-------------|----------|
| Two tables | Lean `score_history` (user_id, captured_at, skill_score) + rich `score_change` (prev/new/delta/cause/reason/diff) | ✓ |
| One combined table | Single `score_event` row holding both score point and change fields | |

**User's choice:** Two tables.
**Notes:** `/history` stays lean and indexed; drill-down weight isolated in `score_change.diff`.
Locked-by-SPEC (not re-asked): both tables get one row per user-with-data every recompute even at
delta=0; all rows in a recompute share one `captured_at` (reuse existing `computed_at`).

---

## Drill-down diff storage

| Option | Description | Selected |
|--------|-------------|----------|
| Precomputed impact array | Store per-map `{prev, new, impact}` deltas; conservation enforced at write | ✓ |
| Full prev + new breakdown | Store both complete breakdowns; impacts computed at read time (~2× storage) | |
| New breakdown only | Store new breakdown; diff against prior change row at read (fragile) | |

**User's choice:** Precomputed impact array.
**Notes:** `impact = new_contribution − prev_contribution`; dropped map → new=0, appeared map → prev=0;
gamma-decay rank shifts captured automatically. Wiring note: `_do_recompute` must read the prior
snapshot's score + breakdown before `replace_snapshot` TRUNCATEs.

### Sub-decision: cutoff time (where top-N split happens)

| Option | Description | Selected |
|--------|-------------|----------|
| Store all impacts, cut at read | diff holds every map's impact; endpoint applies top-N at read; N tunable forever | ✓ |
| Bake top-N at write | diff stores only top-N + precomputed other_factors; N frozen into history | |

**User's choice:** Store all impacts, cut at read.

---

## Top-N cutoff

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed top 5 by \|impact\| | List 5 largest movers, roll rest into other_factors (tunable constant) | ✓ |
| Fixed top 3 | Tighter list, more in other_factors | |
| Magnitude threshold | List maps above an impact threshold; variable row count | |
| You decide | Defer to Claude | |

**User's choice:** Fixed top 5 by |impact|.

---

## Cause attribution

### Per-user cause for a single clean completion trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Actor = PLAYER, others = MAP | Actor X → PLAYER_ACTION; every other user-with-data → MAP_ENVIRONMENT | ✓ |
| Actor = PLAYER, only movers = MAP | X → PLAYER; delta≠0 others → MAP; delta=0 bystanders → SYSTEM | |
| Whole recompute, one cause | Entire recompute tagged by trigger (verify → everyone PLAYER_ACTION) | |

**User's choice:** Actor = PLAYER, others = MAP.
**Notes:** Bystanders with delta=0 still get a MAP_ENVIRONMENT row (one row per user per recompute is
locked). SYSTEM (config/tier/nightly/coalesced) → everyone SYSTEM "global recalculation" (SPEC-locked).

### Threading mechanism + coalescing detection

| Option | Description | Selected |
|--------|-------------|----------|
| Structured event + guard accumulator | Typed `cause_category`+`actor_user_id` on event; `_RecomputeGuard` accumulates descriptors; 1 completion → actor/PLAYER+MAP, 2+ or any SYSTEM → everyone SYSTEM | ✓ |
| Parse reason string + actor field | Derive category by parsing reason suffix; thread actor separately; coalesce counter | |
| You decide | Defer to Claude | |

**User's choice:** Structured event + guard accumulator.

---

## Claude's Discretion

- Pagination: `limit`+`offset` to match the codebase (tournaments routes).
- msgspec response struct field layouts; column/index names; `cause_category` as text+CHECK / Literal
  rather than DB enum.
- Descriptor struct shape inside `_RecomputeGuard` and enriched event field names.
- Window→interval mapping and summary anchoring math (SPEC-specified).
- Deterministic test triggering of recompute (single-trigger PLAYER/MAP path + coalesced SYSTEM path).

## Deferred Ideas

- Retention pruning / downsampling (out of scope; unbounded forward-only for now).
- Website dashboard UI and Discord `/skill` history surface (later phases).
- Cursor pagination for the change feed (offset sufficient at current scale).
- Manual admin recompute / on-demand recovery endpoint (carried from Phase 13).
