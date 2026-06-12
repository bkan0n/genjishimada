---
phase: 13-skill-score
plan: 04
subsystem: api
tags: [skill-score, scorer, msgspec, asyncpg, diminishing-returns, farming-resistance, in-flight-guard]

# Dependency graph
requires:
  - phase: 13-02
    provides: "Weights / SkillConfigUpdateRequest / SkillSummaryResponse / SkillBreakdownRow SDK structs"
  - phase: 13-03
    provides: "SkillRepository.fetch_skill_inputs / fetch_weights / replace_snapshot / fetch_snapshot / update_weights"
provides:
  - "SkillService: the ported hybrid scorer (floor + video-gated proof multipliers + field-size shrink + Σ sᵢ/iᵞ), proven equivalent to the spike within 1e-6 across all 261 real-data players"
  - "recompute_all — THE single rebuild routine (event + nightly + PATCH) with a process-wide in-flight collapse guard (D-05)"
  - "get_user_skill / get_user_breakdown read methods honoring the D-07 empty-player rule and decoding the D-06 JSONB breakdown"
  - "get_weights / update_weights (pure write, gamma>=0.5 guard)"
  - "provide_skill_service DI provider"
  - "InvalidGammaError domain exception"
affects: [13-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level helper functions for a ported pure-math scorer, taking the SDK Weights struct (no weight literals — SPEC req 5)"
    - "Process-wide in-flight collapse guard (module-scope _RecomputeGuard with lazy asyncio.Lock + rerun flag) for DI-per-request services"
    - "importlib-loaded spike reference scorer as the equivalence oracle in a pure-Python (no-DB) unit test"

key-files:
  created:
    - apps/api/services/skill_service.py
    - apps/api/services/exceptions/skill.py
    - apps/api/tests/services/test_skill_scorer.py
    - apps/api/tests/services/test_skill_service.py
  modified:
    - apps/api/pyproject.toml

key-decisions:
  - "In-flight guard (D-05) is a module-scope _RecomputeGuard object (lazy asyncio.Lock + rerun flag), not a per-instance lock: Litestar builds a fresh SkillService per request via DI, so only a process-wide guard coalesces a burst across requests."
  - "gamma<0.5 rejection is a domain exception (InvalidGammaError, mirrors tournaments exception convention) raised before the write; the DB CHECK is the backstop (T-13-09)."
  - "update_weights builds the partial-update dict via msgspec.structs.asdict + UNSET filter; the route owns the post-PATCH recompute (D-10), keeping update_weights a pure write."

patterns-established:
  - "Scorer = module-level pure functions (_diff_weight/_map_score/_player_score/_player_breakdown) over the Weights struct; the service only orchestrates."
  - "Equivalence test imports the spike score.py by file path (registered in sys.modules before exec so its @dataclass annotation resolution works) and asserts per-user parity within 1e-6."

requirements-completed: [4, 5]

# Metrics
duration: ~35min
completed: 2026-06-12
---

# Phase 13 Plan 04: Skill Scorer Service Summary

**Ported the spike's hybrid farming-resistance scorer into `SkillService` — proven equivalent to the spike within 1e-6 across all 261 real-data players — with the single `recompute_all` rebuild routine, a process-wide in-flight collapse guard, and the D-07/D-06-honoring read methods, all reading weights from the DB config with zero weight literals.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-12
- **Tasks:** 2
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments
- Ported `score.py:44-106` (`diff_weight`, `map_score`, `player_score`, `player_breakdown`) into module-level helpers over the SDK `Weights` struct — **no weight literal anywhere** in the service (SPEC req 5; grep for `1.44/0.68/0.55/10.0/0.60/1.12/…` returns nothing).
- Equivalence test loads the cached real inputs + the spike scorer and asserts `SkillService._player_score` equals `score.player_score` within 1e-6 for **every** of the 261 users; plus partial=floor-only<video and the gamma-dial break-even drop.
- `recompute_all`: fetch_weights → `msgspec.convert(Weights)` → fetch_skill_inputs → group-by-user → score + capture per-map breakdown (D-06) → `replace_snapshot` (lean, D-07), wrapped in a process-wide in-flight collapse guard (D-05/T-13-08) that coalesces a burst into at most one extra rebuild.
- Read methods: `get_user_skill` (empty-player → all-zero summary), `get_user_breakdown` (empty → `[]`, else decode JSONB into `list[SkillBreakdownRow]`), `get_weights`; `update_weights` rejects gamma<0.5 (`InvalidGammaError`) before writing only the non-UNSET fields.

## Task Commits

Each task was committed atomically:

1. **Task 1: Port the hybrid scorer + spike-equivalence test (RED→GREEN)** - `10e6586` (feat)
2. **Task 2: recompute_all + in-flight guard + read methods** - `017fafa` (feat)

_Task 1 combined the RED test and GREEN implementation into one atomic feat commit (the plan's Task 1 produces both files as one deliverable)._

## Files Created/Modified
- `apps/api/services/skill_service.py` - The scorer (module helpers) + `SkillService` (recompute_all, get_user_skill, get_user_breakdown, get_weights, update_weights) + `_RecomputeGuard` + `provide_skill_service`.
- `apps/api/services/exceptions/skill.py` - `SkillError` / `InvalidGammaError` (gamma>=0.5 guard).
- `apps/api/tests/services/test_skill_scorer.py` - Spike-equivalence (1e-6 over all users), partial<video, gamma break-even dial.
- `apps/api/tests/services/test_skill_service.py` - recompute grouping+replace, breakdown sums to total, concurrent-burst collapse, empty-player rules, gamma guard.
- `apps/api/pyproject.toml` - Registered the `domain_skill` pytest marker.

## Decisions Made
- **In-flight guard at module scope, not per-instance** (D-05): DI constructs a fresh `SkillService` per request, so a per-instance `asyncio.Lock` would never coalesce a burst across requests. A single module-level `_RecomputeGuard` (lazy lock created on first use to bind the running loop + a `rerun_requested` flag) is the correct one-per-process guard. The holder loops once more after finishing if a rerun was requested, so the final snapshot reflects the latest inputs.
- **gamma guard as a domain exception** (`InvalidGammaError`), mirroring the tournaments exception convention, so plan 13-05's controller can map it to a 4xx; the DB `CHECK (gamma >= 0.5)` remains the backstop (T-13-09).
- **update_weights stays a pure write** — the immediate full recompute on PATCH (D-10) is left to the route (plan 13-05).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected the equivalence-test fixture path + registered the `domain_skill` marker**
- **Found during:** Task 1
- **Issue:** (a) The plan's `read_first` referenced `sources/001-skill-input-query/skill_inputs.json`, but that cached-inputs file does not exist under the skill `sources/` — it lives at `.planning/spikes/001-skill-input-query/skill_inputs.json`. (b) The test uses `@pytest.mark.domain_skill`, which was unregistered (pyproject `markers` listed every other domain but not skill), which would raise under the strict-marker config.
- **Fix:** (a) Pointed the test at the `.planning/spikes/001-…/skill_inputs.json` path that actually exists (the spike `score.py` it imports is byte-identical between the skill `sources/` copy and `.planning/spikes/`, verified via diff). (b) Added `domain_skill` to the `markers` list in `apps/api/pyproject.toml`.
- **Files modified:** apps/api/tests/services/test_skill_scorer.py, apps/api/pyproject.toml
- **Verification:** `pytest test_skill_scorer.py` collects and passes; `just lint-api` clean.
- **Committed in:** `10e6586` (Task 1 commit)

**2. [Rule 3 - Blocking] Registered the importlib-loaded spike module in `sys.modules` before exec**
- **Found during:** Task 1
- **Issue:** Loading the spike `score.py` via `importlib` raised `AttributeError: 'NoneType' object has no attribute '__dict__'` — its `@dataclass Weights` (with a `field(default_factory=...)`) resolves field annotations against `sys.modules[cls.__module__]` during class creation, which is absent for a path-loaded module.
- **Fix:** Set `sys.modules[spec.name] = module` before `spec.loader.exec_module(module)`.
- **Files modified:** apps/api/tests/services/test_skill_scorer.py
- **Verification:** Equivalence test passes across all 261 users within 1e-6.
- **Committed in:** `10e6586` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking; test-infrastructure only, no production-code scope change)
**Impact on plan:** Both were necessary to make the equivalence test run at all; the scorer and service match the plan exactly. No scope creep.

## Issues Encountered
- A `PLW0603` (discouraged `global` statement) lint error from the first in-flight-guard draft (rebinding a module-level `_rerun_requested`) was resolved by encapsulating the in-flight state in the module-level `_RecomputeGuard` object and mutating its attribute instead of rebinding a global — same per-process semantics, lint-clean.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `SkillService` is ready for plan 13-05 to wire: the in-process recompute event/listener (D-01/D-02), the `routes/v3/skill.py` controller (the four endpoints; PATCH→`recompute_all` per D-10), the nightly app-side rebuild backstop (D-03), and the community-leaderboard `skill_score` column.
- The human-check in Task 2 (real migrated DB seeded with spike fixtures: recompute_all then get_user_skill/get_user_breakdown parity, concurrent recompute non-overlap) is best exercised in 13-05's integration suite once the endpoints + event wiring exist.

## Self-Check: PASSED

All created files exist on disk; both task commits (`10e6586`, `017fafa`) are present in git history.

---
*Phase: 13-skill-score*
*Completed: 2026-06-12*
