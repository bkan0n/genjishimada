# Phase 12 — Deferred Items

Out-of-scope discoveries during execution. NOT fixed in the discovering plan.

## From Plan 12-01 (DB foundation)

Migration 0024 intentionally drops per-category `cycle_frequency` /
`transitions_paused` / `debug_cycle_seconds` (D-02/D-03) and replaces
`process_cycle_transitions()` semantics with the edition model. This leaves the
following pre-existing tests asserting the OLD model. They are stale-by-design
and are owned by downstream plans that rewrite the SDK / repo / service:

| Test | Why stale | Owning plan |
|------|-----------|-------------|
| `tests/repository/tournaments/test_cycle_transitions.py` (all classes) | Invokes `process_cycle_transitions()` + `create_test_category(cycle_frequency=...)`; the old per-category function/columns are gone. Edition behavior is now covered by `test_edition_transitions.py`. | 12-02 / 12-03 (SDK + service rewrite); these old tests to be removed/rewritten |
| `tests/repository/tournaments/test_lifecycle_control.py::TestSetCategoryPaused`, `TestSetCategoryDebugCycleSeconds` | Exercise `set_category_paused` / `set_category_debug_cycle_seconds` repo methods; pause/debug move to global config setters. | 12-03 (service/repo global setters) |
| `tests/repository/tournaments/test_tournaments_repository.py::TestCreateCategory` (`test_create_category_returns_dict`, `test_create_category_duplicate_name_raises`) | `create_category` repo path still references the dropped `cycle_frequency` column. | 12-02/12-03 (repo update) |

These were NOT modified in 12-01 because they fall outside this plan's
`files_modified` set and depend on SDK/repo/service changes scheduled for later
waves. The in-scope schema test (`test_tournaments_schema.py`) was updated.

## From Plan 12-03 (service + outbox wave) — still deferred

12-03 rewrote the bootstrap/pause/debug service surface and the outbox publisher
to the edition model. The following remain stale-by-design (NOT in 12-03's
`files_modified`, and resolving them requires reshaping the category SDK structs
+ integration assertions, which spans the SDK (12-02) and route (12-04) waves):

| Test | Why stale | Owning plan |
|------|-----------|-------------|
| `tests/integration/test_tournaments_integration.py` (TestCreateCategory + every class whose setup creates a category via `POST /categories`) | `create_category` repo path + service call still bind the dropped `cycle_frequency` column → `POST /categories` returns 500; the SDK `TournamentCategoryCreateRequest`/`TournamentCategoryResponse` still require `cycle_frequency`. A coordinated SDK + repo + service + integration-test change (drop per-category `cycle_frequency`, use the global `cadence`) is needed. | 12-04 (route/SDK alignment) — `create_category` cleanup |
| `tests/repository/tournaments/test_cycle_transitions.py` (all classes) | Invokes the removed `process_cycle_transitions()` + `create_test_category(cycle_frequency=...)`. Edition behavior is covered by `test_edition_transitions.py`; this file should be removed/rewritten. | 12-04 (cleanup) |
| `tests/repository/tournaments/test_lifecycle_control.py::TestSetCategoryPaused`, `TestSetCategoryDebugCycleSeconds` (`*_returns_none`) | The per-category repo shims now delegate to the global setters and return the config singleton (a dict) rather than None. Pause/debug are global since 0024. Service-level behavior is covered by `test_tournament_lifecycle.py`. | 12-04 (cleanup) |

`tests/integration/test_tournament_rewards.py` WAS updated in 12-03 (its outbox
seed now emits an `edition_rollover` row whose `results` carry the per-cycle
completed entry) because 12-03's outbox rewrite directly drove the breakage and
the reward/streak/ledger behavior under test is preserved per child cycle.

## Resolved in Plan 12-04 (route wave)

12-04 completed the coordinated `cycle_frequency` cleanup that the rows above
assigned to this wave (cadence is GLOBAL on `tournaments.config` since 0024):

- Dropped `cycle_frequency` from the three category SDK structs
  (`TournamentCategoryResponse` / `…CreateRequest` / `…PatchRequest`), the repo
  `create_category` INSERT, and the service `create_category` / `update_category`.
- Fixed the now-broken downstream callers (bot `/tournament info` no longer
  derives `ends_at` from cadence — it reads the stored edition `ends_at` via the
  new `GET /editions/active`; bot/test fixtures dropped `cycle_frequency`).
- `tests/integration/test_tournaments_integration.py` (was 26 failing → green),
  `tests/repository/tournaments/test_tournaments_repository.py::TestCreateCategory`
  (was xfail → green): all resolved.

### Still deferred after 12-04

These remain stale-by-design (NOT in 12-04's `files_modified`; they exercise the
removed `process_cycle_transitions()` / per-category None semantics, covered
elsewhere by `test_edition_transitions.py` / `test_tournament_lifecycle.py`):

- `tests/repository/tournaments/test_cycle_transitions.py` (5) — calls removed
  `tournaments.process_cycle_transitions()` + `cat.cycle_frequency`.
- `tests/repository/tournaments/test_lifecycle_control.py::TestSetCategoryPaused`,
  `TestSetCategoryDebugCycleSeconds` (2 `*_returns_none`).
