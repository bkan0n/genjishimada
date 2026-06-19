---
phase: 14-skill-score-dashboard
plan: 04
subsystem: skill-dashboard-capture-cause-reads
tags: [skill-score, capture, cause-attribution, events, read-methods, conservation]

# Dependency graph
requires:
  - phase: 14-skill-score-dashboard
    provides: "SkillRepository capture+read methods + CompletionsRepository.fetch_completion_owner_by_message — Plan 14-03"
  - phase: 14-skill-score-dashboard
    provides: "SDK history/feed/drill-down response structs + CauseCategory + enriched SkillRecomputeRequestedEvent — Plan 14-02"
provides:
  - "skill_service._do_recompute capture wiring + TriggerDescriptor + _RecomputeGuard.pending accumulator + cause policy (Task 1, pre-committed 251b276)"
  - "events/skill.py listener threads the typed TriggerDescriptor into recompute_all"
  - "completions_service._emit_skill_recompute(cause_category, actor_user_id); 5 emit sites pass owner id"
  - "flag/unflag emit sites resolve owner via self._completions_repo.fetch_completion_owner_by_message (A4)"
  - "SkillService.get_user_history / get_user_changes / get_user_change_detail read methods (empty rule, summary anchoring, top-N drill-down)"
affects:
  - "14-05 dashboard routes (call the three read methods; pass cause descriptors on PATCH config)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Typed cause descriptor threaded end-to-end (event → listener → recompute_all → drained accumulator) — no reason-string parsing"
    - "Owner lookup at flag/unflag via the service's OWN repo (no cross-service private-attribute access)"
    - "Read-time top-N cut: sort diff.maps by abs(impact) desc, list top _TOP_N, residual tail → other_factors (conservation by residual)"
    - "Empty rule: read methods return documented empty/zero shapes, never 500, never synthetic rows"

key-files:
  created: []
  modified:
    - "apps/api/events/skill.py (build TriggerDescriptor from event.cause_category/actor_user_id; thread into recompute_all)"
    - "apps/api/services/completions_service.py (_emit_skill_recompute gains cause_category+actor_user_id; 5 sites pass owner id; flag/unflag owner lookup)"
    - "apps/api/services/skill_service.py (+_window_since helper + 3 read methods + SDK struct imports; Task 1 capture/cause already committed 251b276)"
    - "apps/api/tests/services/test_skill_service.py (+4 tests: cause split, coalesced→SYSTEM, prev-before-truncate, conservation)"

key-decisions:
  - "Listener passes a TriggerDescriptor; cause resolved from the typed accumulator (T-14-10) — never by parsing the reason string"
  - "flag/unflag resolve actor_user_id via self._completions_repo.fetch_completion_owner_by_message (A4); None falls back to SYSTEM via the policy's lone-no-actor branch"
  - "get_user_change_detail derives the per-map SkillChangeCause.reason from the change row's reason (cause_category fallback) — the stored diff carries no per-map reason"
  - "PATCH /skill/tiers (update_tier_config) left untouched per A1 — no score moves → no capture rows"

requirements-completed: [REQ-14-1, REQ-14-2, REQ-14-3, REQ-14-4, REQ-14-5, REQ-14-7]

# Metrics
duration: ~12min
completed: 2026-06-16
tasks: 3
files: 4
---

# Phase 14 Plan 04: Capture Wiring + Cause Policy + Read Methods Summary

**The core of Phase 14: capture (history + per-change) rides the single `_do_recompute` routine reading the prev snapshot before TRUNCATE; a typed `TriggerDescriptor` accumulator resolves per-user cause (actor PLAYER_ACTION / bystander MAP_ENVIRONMENT / coalesced+nightly SYSTEM); the listener and five `completions_service` emit sites thread the typed cause + completion-owner id (flag/unflag use the A4 owner lookup); and three service read methods (history+summary, paginated feed, top-5 drill-down) honor the empty rule. Scorer untouched, conservation exact, `just lint-api` clean.**

## Resume Context

**Task 1 was already complete and committed (`251b276`) before this executor started** — the capture wiring in `_do_recompute`, the `TriggerDescriptor` dataclass, the `_RecomputeGuard.pending` accumulator (drained inside the rerun loop, Pitfall 2), the `_resolve_cause_policy` helper, and the `_build_diff` conservation join. This executor verified Task 1's work (drain-inside-loop confirmed correct; `_reset_guard` already clears `pending` in both halves) and implemented **Task 2 + Task 3** on top without altering Task 1.

## Accomplishments

**Task 2 — Thread cause + owner; add read methods** (`8b147c3`):
- `events/skill.py`: builds `TriggerDescriptor(cause_category=event.cause_category, actor_user_id=event.actor_user_id)` and passes it to `recompute_all(descriptor)`; the log-and-continue try/except (no re-raise) is retained; log line extended with `cause`/`actor` (`%s` formatting).
- `_emit_skill_recompute`: gains keyword-only `cause_category: str = "SYSTEM"` + `actor_user_id: int | None = None`; constructs the enriched `SkillRecomputeRequestedEvent`; None-guard kept.
- Five emit sites all pass `cause_category="PLAYER_ACTION"` + the completion owner:
  - verify / un-verify → `actor_user_id=completion_info["user_id"]` (in scope).
  - moderate → `actor_user_id=user_id` (in scope at line 1465).
  - flag (`set_suspicious_flags`) / unflag (`remove_suspicious_flags`) → `owner_id = await self._completions_repo.fetch_completion_owner_by_message(data.message_id, data.verification_id)` BEFORE each emit (A4 — the service's OWN repo; no `skill_service._skill_repo` access). `None` (vanished completion) falls back to SYSTEM via the policy's lone-no-actor branch.
- `update_tier_config` (PATCH /skill/tiers) left untouched per A1 — no score moves → no capture rows.
- Three read methods on `SkillService` (each honoring SPEC req 7 empty rule):
  - `get_user_history(user_id, window)` → `SkillHistoryResponse`. Maps window→`since` via `_window_since` (`all`→`_EPOCH`); builds `SkillHistoryPoint` list; summary anchored on the earliest in-window record (`point_change = last - first`, `percent_change = point_change/first*100` guarded at `first==0`, `best`/`lowest` = max/min point + date, `average` = mean). Empty → `points=[]` + all-zero summary (extrema date `None`).
  - `get_user_changes(user_id, window, limit, offset)` → `list[SkillChangeFeedItem]`; `description` from `reason` (cause-category fallback). Empty → `[]`.
  - `get_user_change_detail(user_id, change_id)` → `SkillChangeDetailResponse | None`. Ownership-checked repo read → `None` (route 404). Sorts `diff.maps` by `abs(impact)` desc, lists top `_TOP_N` as `main_causes`, sums the tail into `other_factors` (conservation by residual); `percent_change = delta/previous_score*100` guarded at `prev==0`.

**Task 3 — Service tests** (`9fdfbed`):
- `_reset_guard` already clears `_GUARD.pending` in both halves (Task 1) — verified, no change needed.
- `test_recompute_player_action_splits_actor_and_bystander`: ONE PLAYER_ACTION descriptor (actor uid 1) → actor row `PLAYER_ACTION`, bystander row `MAP_ENVIRONMENT`, reason "verified completion".
- `test_recompute_coalesced_burst_promotes_to_system`: pre-load a 2nd descriptor → single recompute drains ≥2 → every change row `SYSTEM` "global recalculation".
- `test_recompute_reads_prev_snapshot_before_truncate`: non-empty `fetch_all_snapshots` → 2nd recompute's `previous_score == 3.0`, `delta == new - prev` (Pitfall 1).
- `test_recompute_change_diff_conserves`: prev≠new breakdown → `Σ diff.maps[*].impact ≈ delta` within 1e-6.

## Verification Results

- **Task 2 verify:** `tests/services/test_skill_service.py` → 10 passed (pre-Task-3); threading greps: `actor_user_id` present in `events/skill.py`; `fetch_completion_owner_by_message` count = 2 (flag + unflag); no `skill_service._skill_repo` in `completions_service.py`; `_TOP_N` present.
- **Task 3 verify:** `tests/services/test_skill_service.py tests/services/test_skill_scorer.py -x` → **19 passed** (14 service incl. 4 new + 3 scorer + 2 deselected markers).
- **Existing integration:** `tests/integration/test_skill.py -x` → **15 passed, 4 deselected** — no Phase 13 regression.
- **Scorer immutability:** `git diff 251b276 HEAD -- skill_service.py` shows NO removed/modified lines inside `_diff_weight`/`_map_score`/`_player_score`/`_player_breakdown` (only the file-header `---` line appears as a `-`); byte-for-byte unchanged.
- **`just lint-api`:** ruff format/check + basedpyright → `All checks passed!` / `0 errors, 0 warnings, 0 notes`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Self-introduced undefined helper `points_src(rows)` corrected inline**
- **Found during:** Task 2 (writing `get_user_history`).
- **Issue:** The first draft of the points comprehension referenced a non-existent `points_src(rows)` wrapper.
- **Fix:** Replaced with direct iteration `for r in rows`. Caught before any commit/lint; no functional impact.
- **Files modified:** `apps/api/services/skill_service.py` (same edit session).
- **Commit:** `8b147c3` (correct form committed).

**Total deviations:** 1 (self-introduced, fixed pre-commit). Plan otherwise executed as written.

## Threat Model Notes

- **T-14-09 (Tampering, cause_category) — mitigated:** the service writes only `PLAYER_ACTION`/`MAP_ENVIRONMENT`/`SYSTEM` resolved from the typed policy; the migration 0031 DB CHECK is the defense-in-depth backstop.
- **T-14-10 (Repudiation, attribution correctness) — mitigated:** cause is resolved from the typed `TriggerDescriptor` accumulator (no `reason`-string parsing) and drained INSIDE the rerun loop so a coalesced burst is correctly promoted to SYSTEM (verified by `test_recompute_coalesced_burst_promotes_to_system`).
- **T-14-11 / T-14-12 — accepted (unchanged):** drill-down diff is public read data; capture volume bounded by the recompute coalescing guard.
- **No new threat surface:** the read methods are service wrappers over the 14-03 repo reads; the owner lookup is an in-domain `core.completions` read; no new endpoints or auth paths introduced here (routes land in 14-05).

## Self-Check: PASSED

- FOUND: apps/api/events/skill.py (TriggerDescriptor threading)
- FOUND: apps/api/services/completions_service.py (_emit_skill_recompute cause+owner; 2 owner lookups)
- FOUND: apps/api/services/skill_service.py (3 read methods + _window_since)
- FOUND: apps/api/tests/services/test_skill_service.py (4 new tests)
- FOUND: commit 8b147c3 (Task 2)
- FOUND: commit 9fdfbed (Task 3)
- FOUND: .planning/phases/14-skill-score-dashboard/14-04-SUMMARY.md

---
*Phase: 14-skill-score-dashboard*
*Completed: 2026-06-16*
