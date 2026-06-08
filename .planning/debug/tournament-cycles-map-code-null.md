---
status: resolved
trigger: "Sentry issue 7525389189 — ValidationError: Expected `str`, got `null` - at `$.map_code` in TournamentsController.list_cycles"
created: 2026-06-04
updated: 2026-06-04
---

# Debug Session: tournament-cycles-map-code-null

## Symptoms

DATA_START
- **Expected behavior:** `GET /api/v3/tournaments/cycles?status=completed&category_id=2&limit=10&offset=10` returns a paginated list of tournament cycles with winner info.
- **Actual behavior:** Request 500s with `ValidationError: Expected \`str\`, got \`null\` - at \`$.map_code\``.
- **Error message:** `ValidationError('Expected \`str\`, got \`null\` - at \`$.map_code\`')`
- **Origin (in app):** `services/tournament_service.py:1280` —
  `cycles=[msgspec.convert(row, TournamentCycleWithWinnerResponse) for row in rows]`
- **Route:** `routes/v3/tournaments.py:840` → `tournament_service.list_cycles(...)`
- **Timeline:** Seen on dev (release 807a94dab3d0e8ba9c4593bf188772683b8a12ef), env=development, 2026-06-04.
- **Reproduction:** Call the cycles list endpoint where the result set contains a cycle whose `map_code` is NULL.
- **Key evidence:** In the failing `rows` payload, cycle `id=30` (Antarctic Peninsula, map_id=852, map_difficulty='Medium') has `map_code: None` while all sibling rows have a string code. The struct field `TournamentCycleWithWinnerResponse.map_code` appears to be typed non-nullable (`str`), so msgspec rejects the NULL.
DATA_END

## Current Focus

- hypothesis: CONFIRMED — `TournamentCycleWithWinnerResponse.map_code` was typed `str` but the underlying cycle→map join can yield NULL `map_code` for maps whose code was released (migration 0019 dropped NOT NULL on `core.maps.code`), causing `msgspec.convert` to fail.
- next_action: (resolved)
- test: msgspec.convert of a row with `map_code=None` into `TournamentCycleWithWinnerResponse`
- expecting: converts to `map_code=None` instead of raising ValidationError

## Evidence

- timestamp: 2026-06-04 — Struct definition `libs/sdk/src/genjishimada_sdk/tournaments.py:386` had `map_code: str` (non-nullable). Sibling nullable fields (`winner_name`, `winner_user_id`) are `str | None` / `int | None`, confirming the struct uses `| None` for nullable columns.
- timestamp: 2026-06-04 — SQL in `apps/api/repository/tournaments_repository.py:984` selects `m.code AS map_code` directly from `core.maps` via `JOIN core.maps m ON m.id = cy.map_id`. No COALESCE; raw column passes through to the struct. `list_cycles` returns cycles of ANY status (including completed/historical), so a cycle can reference a map whose code was later released to NULL.
- timestamp: 2026-06-04 — Migration `apps/api/migrations/0019_release_map_code.sql:9` runs `ALTER TABLE core.maps ALTER COLUMN code DROP NOT NULL;` — the "release map code" feature deliberately makes `core.maps.code` NULL-able. The codebase already accounts for this: `fetch_eligible_maps` (`tournaments_repository.py:1047`) filters `AND m.code IS NOT NULL` when SELECTING a map for a new cycle.
- timestamp: 2026-06-04 — Reproduced + fixed: `uv run python -c "msgspec.convert({...,'map_code':None,...}, TournamentCycleWithWinnerResponse)"` raised the exact ValidationError before the fix and returns `map_code=None` after the fix (string codes still convert).
- timestamp: 2026-06-04 — Consumer safety: all bot consumers of `.map_code` (`apps/bot/extensions/tournaments.py:432,786,964`) operate on `TournamentCycleStartedEvent` / `TournamentNextCycleResponse` — structs sourced from freshly-SELECTED maps (which always have non-NULL codes via the `fetch_eligible_maps` filter), NOT on `TournamentCycleWithWinnerResponse`. The crashing path is the HTTP list endpoint feeding the website. Making the list struct's `map_code` nullable does not affect any bot consumer.

## Eliminated

- The SQL query is NOT the bug — the join is correct; historical cycles legitimately reference maps whose codes have since been released. Excluding/COALESCE-ing NULL codes would hide real cycles from the list and is the wrong fix.
- The other two `map_code: str` structs (`TournamentNextCycleResponse:348`, `TournamentCycleStartedEvent:535`) are NOT the cause — they are populated from freshly-selected maps with guaranteed non-NULL codes and were left non-nullable intentionally.

## Specialist Review

- specialist_hint: python (typescript-expert table maps `python` → `python-expert-best-practices-code-review`).
- Specialist subagent dispatch was NOT executed: this session runs inside a subagent where the Task tool is unavailable, so a nested specialist agent could not be spawned. The fix is a single, idiomatic msgspec field-nullability change consistent with the struct's existing `str | None` conventions, verified by reproduction, lint (ruff), and type-check (basedpyright, 0 errors).

## Resolution

- root_cause: `tournaments.cycles` stores only `map_id` (no code snapshot), so `map_code` is a live join to `core.maps.code`. `list_cycles` lists historical cycles whose joined map may since have had its code released to NULL (migration 0019 + `maps_repository.py:1697`: `UPDATE core.maps SET original_code = code, code = NULL`). The NULL reached `msgspec.convert` and 500-ed the endpoint.
- fix (revised after review): Reverted the struct to `map_code: str` and instead recover the preserved code at the query layer. Changed all four cycle-DISPLAY queries in `apps/api/repository/tournaments_repository.py` from `m.code AS map_code` to `COALESCE(m.code, m.original_code) AS map_code` (`list_cycles`, `fetch_pending_cycle`, `fetch_active_cycle_with_map`, started-event fetch). This shows the code the cycle actually used instead of a blank, and is guaranteed non-NULL: the release op writes `original_code = code` before nulling `code`, and cycles only ever receive maps via `fetch_eligible_maps` (`m.code IS NOT NULL`). The eligible-map SELECTION queries keep `m.code` (they pick new active maps and must not resurrect released codes).
- why not nullable struct: a nullable field would render a blank workshop code on the website for a tournament that genuinely had one. The domain already provides `original_code` for exactly this audit case.
- verification: `ruff check` passes; `basedpyright` reports 0 errors. No raw `m.code AS map_code` remains in display queries; 4 COALESCE'd. Bot consumers (`apps/bot/extensions/tournaments.py`) use `TournamentCycleStartedEvent`/`TournamentNextCycleResponse`, both now COALESCE-fed and `str` — unaffected.
- files_changed: `apps/api/repository/tournaments_repository.py`, `libs/sdk/src/genjishimada_sdk/tournaments.py` (docstring only — field type unchanged from original)
- follow-up: add a regression test asserting `list_cycles` returns the original code for a released-map cycle; run `just test-api` (needs test DB) before merge.
