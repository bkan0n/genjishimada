---
phase: 15-dynamic-overwatch-map-management
plan: 01
subsystem: api
tags: [msgspec, sdk, litestar, asyncpg, pytest, type-alias, validation]

# Dependency graph
requires:
  - phase: (none — Wave 1 root plan, depends_on: [])
    provides: existing OverwatchMap Literal in libs/sdk/.../maps.py and the maps.names seed
provides:
  - "OverwatchMap aliased to `str` (REQ-01): map-name validation removed from the type system at the msgspec decode boundary"
  - "All 9 test-fixture sites use _SEED_MAP_NAMES instead of get_args(OverwatchMap) — suite runs post-flip"
  - "The 70 verbatim map names captured below for plan 15-02 to rewrite the 0001_init.sql seed"
affects: [15-02 (seed rewrite consumes the 70 names + maps.names FK), 15-03 (runtime name validation against maps.names replaces the lost enum gate), 15-04, 15-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Type-alias relaxation with name kept exported in __all__ so all consumers compile untouched (minimal-churn aliasing, Assumption A1)"
    - "Module-level _SEED_MAP_NAMES constant (real maps.names FK targets) replaces get_args() of a now-relaxed Literal in test factories"

key-files:
  created: []
  modified:
    - libs/sdk/src/genjishimada_sdk/maps.py
    - apps/api/tests/conftest.py
    - apps/api/tests/repository/maps/test_maps_repository_create_core_map.py
    - apps/api/tests/repository/maps/test_maps_repository_update_core_map.py
    - apps/api/tests/repository/maps/test_maps_repository_fetch_partial_map.py
    - apps/api/tests/repository/maps/test_maps_repository_advanced_operations.py
    - apps/api/tests/repository/maps/test_maps_repository_entity_operations.py
    - apps/api/tests/repository/maps/test_maps_repository_check_code_exists.py
    - apps/api/tests/repository/maps/test_maps_repository_guide_operations.py
    - apps/api/tests/repository/community/test_community_repository_popular.py

key-decisions:
  - "Kept OverwatchMap defined and in __all__ (aliased to str) rather than deleting it — the ~27 consumer modules keep importing the name with zero edits."
  - "Defined _SEED_MAP_NAMES locally per test file (module top) rather than cross-importing from conftest — matches the existing per-file `fake = Faker()` convention and avoids new test-module coupling."
  - "Chose a 5-name subset (Hanamura, Busan, Ilios, Nepal, Oasis) verified present in the 0001_init.sql maps.names seed — each is a valid core.maps.map_name FK target."

patterns-established:
  - "Pattern 1: When relaxing a Literal that test fixtures enumerate via get_args(), replace with an explicit constant of real DB-seeded values in the same wave — the two changes are inseparable because get_args(str) returns ()."

requirements-completed: [REQ-01, D-04]

# Metrics
duration: 18min
completed: 2026-06-26
---

# Phase 15 Plan 01: Drop the OverwatchMap Literal Summary

**`OverwatchMap = str` in the SDK (REQ-01) — map-name validation moved off the msgspec decode boundary onto the database, with all 9 `get_args(OverwatchMap)` test fixtures repaired to use a real `maps.names` seed subset so the full API suite still runs.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-26 (this session)
- **Completed:** 2026-06-26
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Replaced the closed 70-entry `OverwatchMap = Literal[...]` block with a single `OverwatchMap = str` alias (kept defined + exported in `__all__`), so msgspec now accepts any string map name at the request boundary — the enum gate is gone (REQ-01 / D-04 request-side).
- `MapCategory`, `Mechanics`, `Restrictions`, `Tags`, and `DifficultyAll` remain strict Literals (verified: `get_args(MapCategory)` still returns its 3 values).
- Repaired all 9 fixture sites (`conftest.py` + 8 test files) that called `get_args(OverwatchMap)` — without this the flip makes `fake.random_element([])` raise and blocks the whole API suite. Each now draws from a module-level `_SEED_MAP_NAMES` constant of real seed rows.
- Full API suite green post-flip: **1722 passed, 2 skipped, 2 xfailed, 0 failures**; zero `get_args(OverwatchMap)` references remain across `apps/api/tests/`.
- Captured the 70 verbatim map names below for plan 15-02's seed rewrite.

## Task Commits

Each task was committed atomically:

1. **Task 1: Flip OverwatchMap Literal to str in the SDK** - `f8e7b24` (feat)
2. **Task 2: Replace get_args(OverwatchMap) with _SEED_MAP_NAMES in 9 fixture sites** - `56e5ce5` (test)

## Files Created/Modified

- `libs/sdk/src/genjishimada_sdk/maps.py` - `OverwatchMap = str` (was a 70-entry Literal); kept exported; other Literals untouched.
- `apps/api/tests/conftest.py` - Added module-level `_SEED_MAP_NAMES`; removed the dead `get_args` / `MapCategory, OverwatchMap` factory imports (the factory already used string literals `"Hanamura"`/`"Classic"`).
- `apps/api/tests/repository/maps/test_maps_repository_create_core_map.py` - `_SEED_MAP_NAMES` for `map_name`; dropped `OverwatchMap` import; kept `get_args(MapCategory)` + `get_args(PlaytestStatus)`.
- `apps/api/tests/repository/maps/test_maps_repository_update_core_map.py` - same pattern.
- `apps/api/tests/repository/maps/test_maps_repository_fetch_partial_map.py` - same pattern.
- `apps/api/tests/repository/maps/test_maps_repository_advanced_operations.py` - same pattern (positional usage).
- `apps/api/tests/repository/maps/test_maps_repository_entity_operations.py` - same pattern.
- `apps/api/tests/repository/maps/test_maps_repository_check_code_exists.py` - same pattern.
- `apps/api/tests/repository/maps/test_maps_repository_guide_operations.py` - same pattern.
- `apps/api/tests/repository/community/test_community_repository_popular.py` - `_SEED_MAP_NAMES` at module top; dropped `OverwatchMap` from the two function-local imports; kept `get_args(MapCategory)`.

## The 70 verbatim OverwatchMap names (for plan 15-02 seed rewrite)

These are the exact 70 string literals removed from the `OverwatchMap` Literal, in original order. They match the `maps.names` seed rows in `apps/api/migrations/0001_init.sql`. The 7 phantom maps flagged by the plan (Arena Victoriae, Redwood Dam, Thames District, Gogadoro, Powder Keg Mine, Place Lacroix, Neon Junction) are included.

1. Circuit Royal
2. Runasapi
3. Practice Range
4. Route 66
5. Midtown
6. Junkertown
7. Colosseo
8. Lijiang Tower (Lunar New Year)
9. Dorado
10. Throne of Anubis
11. Castillo
12. Blizzard World (Winter)
13. Hollywood (Halloween)
14. King's Row
15. Black Forest (Winter)
16. Petra
17. Framework
18. Eichenwalde
19. Workshop Island
20. Chateau Guillard (Halloween)
21. New Junk City
22. Necropolis
23. Kanezaka
24. Havana
25. Oasis
26. Ayutthaya
27. Volskaya Industries
28. Hanamura
29. Workshop Expanse
30. Hanaoka
31. Lijiang Tower
32. Busan (Lunar New Year)
33. Suravasa
34. King's Row (Winter)
35. Ecopoint: Antarctica
36. Hanamura (Winter)
37. Blizzard World
38. Chateau Guillard
39. Paraiso
40. Workshop Green Screen
41. Watchpoint: Gibraltar
42. Shambali
43. Eichenwalde (Halloween)
44. Tools
45. Nepal
46. Samoa
47. Horizon Lunar Colony
48. Paris
49. Esperanca
50. Black Forest
51. Antarctic Peninsula
52. Workshop Chamber
53. Hollywood
54. New Queen Street
55. Rialto
56. Busan
57. Malevento
58. Temple of Anubis
59. Ilios
60. Ecopoint: Antarctica (Winter)
61. Numbani
62. Adlersbrunn
63. Aatlis
64. Arena Victoriae
65. Redwood Dam
66. Thames District
67. Gogadoro
68. Powder Keg Mine
69. Place Lacroix
70. Neon Junction

## Decisions Made

- Aliased rather than deleted `OverwatchMap` so the ~27 consumer modules (SDK struct fields, API repo/route/service hints, bot hints) compile untouched (Assumption A1).
- Used per-file module-level `_SEED_MAP_NAMES` constants instead of a shared conftest import — keeps the test files self-contained, mirroring the existing per-file `fake = Faker()` convention.
- Removed (did not just unuse) the dead `get_args`/`OverwatchMap`/`MapCategory` imports in `conftest.py`'s factory, since that factory already hardcoded `"Hanamura"`/`"Classic"` and the imports would otherwise be unused (lint failure).

## Deviations from Plan

None — plan executed exactly as written. The plan's note about the RESEARCH "14 files" overcount was confirmed: a live grep returned exactly 8 test files + `conftest.py` = 9 sites, all repaired; zero sites under `apps/bot/tests/`.

## Issues Encountered

- The Phase-15 explanatory comments I added initially contained the literal substring `get_args(OverwatchMap)`, which would have caused the success-criterion backstop grep (`grep -rln 'get_args(OverwatchMap)' apps/api/tests/`) to report 9 files (all comments, no code). Reworded the comments to "calling get_args on the old OverwatchMap Literal" so the grep returns ZERO files, satisfying the success criterion precisely. No code behavior affected.

## Security / Threat Notes

- **T-15-01 (Tampering/Elevation):** This plan ONLY relaxes the type. The enum check the Literal gave for free is NOT yet replaced — that runtime gate against `maps.names` (plan 15-03, REQ-02) plus the `core.maps.map_name` FK backstop (plan 15-02, REQ-11) are required before this surface ships. msgspec still enforces field presence/type (missing/non-string name → 400). Encoded as a hard dependency for Wave 2.
- **T-15-02 (Info disclosure):** Only the map-name Literal was relaxed; `MapCategory`/`Mechanics`/`Difficulty` stay strict (acceptance test asserts `get_args(MapCategory)` length 3). No new surface introduced by this plan.

No new threat surface beyond the planned T-15-01 relaxation was introduced.

## Next Phase Readiness

- **15-02 (seed rewrite):** Ready — the 70 verbatim names are captured above; the `maps.names` FK target list is confirmed present in `0001_init.sql`.
- **15-03 (runtime validation):** BLOCKING DEPENDENCY — the lost enum gate MUST be replaced by a service-layer check against `maps.names`. This plan deliberately ships only the type relaxation.
- Verification environment: `just lint-sdk` clean, `just lint-api` clean, `just test-api` full suite green (1722 passed).

## Self-Check: PASSED

- FOUND: `libs/sdk/src/genjishimada_sdk/maps.py` (contains `OverwatchMap = str`)
- FOUND: `apps/api/tests/conftest.py`
- FOUND: `.planning/phases/15-dynamic-overwatch-map-management/15-01-SUMMARY.md`
- FOUND commit `f8e7b24` (Task 1)
- FOUND commit `56e5ce5` (Task 2)

---
*Phase: 15-dynamic-overwatch-map-management*
*Completed: 2026-06-26*
