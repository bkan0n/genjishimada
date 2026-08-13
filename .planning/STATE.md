---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: — Phases
status: milestone_complete
last_updated: "2026-06-26T03:01:08.149Z"
last_activity: 2026-06-26
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 26
  completed_plans: 26
  percent: 100
---

# Tournament System — State

Last activity: 2026-06-29 - Completed quick task 260629-caz: Add GET /store/admin/quests list-all endpoint

## Current Status

Milestone v1.0 (recurring tournament cycles) is **shipped** — phases 01–11
complete and committed on `feat/tournaments-pr` (`52b066e feat(tournaments):
tournament verification system (GSD v1.0, phases 01-11)`).

## What's Built

Tournament domain within the Genji Shimada monorepo, following the existing
Controller → Service → Repository pattern:

- **Migrations:** `apps/api/migrations/0020_tournaments.sql`, `0021_tournament_cycle_transitions.sql`, `0022_tournament_xp_grants.sql` (`tournaments` schema; `core.completions.tournament_completion_id` FK).
- **SDK:** `libs/sdk/src/genjishimada_sdk/tournaments.py` (msgspec structs + events).
- **Repository:** `apps/api/repository/tournaments_repository.py`.
- **Services:** `apps/api/services/tournament_service.py`, `tournament_outbox_service.py`, `tournament_reward_service.py`; exceptions in `apps/api/services/exceptions/tournaments.py`.
- **Routes:** `apps/api/routes/v3/tournaments.py`.
- **Bot:** `apps/bot/extensions/tournaments.py` (queue consumers, announcements, admin slash commands).
- **Cycle transitions:** automatic rollover via pg_cron + outbox/poller (Phase 07).

## Key Decisions (carried forward)

- Separate `tournaments.completions` table; cross-write to `core.completions` only when strictly faster (preserves "latest = fastest").
- Tier-then-time ranking (verified > unverified, then fastest).
- Automatic cycle transitions via pg_cron + outbox poller.
- XP via existing `api.xp.grant` queue with deterministic keys for double-grant prevention.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260601-bhy | Tournament cycle lifecycle control: bootstrap first cycle, pause/resume, debug cycle-length override | 2026-06-01 | 0df17d6 | [260601-bhy-tournament-cycle-lifecycle-control-boots](./quick/260601-bhy-tournament-cycle-lifecycle-control-boots/) |
| 260601-ui4 | Fix tournament verify hang: PB propagation resolved cycle via active-only lookup, so verifying during a `finalizing` cycle never drained the gate (edition stuck in awaiting_results, no results announcement) | 2026-06-02 | 527a7ad | [260601-ui4-tournament-verification-needs-to-be-bake](./quick/260601-ui4-tournament-verification-needs-to-be-bake/) |
| 260602-d96 | Fix tournament end announcements: poller now populates rollover `started` from the active edition (was always `[]` → no new-cycle info + misleading "new rotation arrived" title); transition-accurate bot framing; dedupe winner mentions to fix results-card `50035` DLQ crash on multi-category winners | 2026-06-02 | b605b2f | [260602-d96-fix-tournament-end-announcements-poller-](./quick/260602-d96-fix-tournament-end-announcements-poller-/) |
| 260602-dpm | Bootstrap UX: `debug_cycle_seconds` anchors first edition at server `now()` (no manual re-anchor in tests; prod weekly/biweekly `next_grid_boundary` path unchanged); bootstrap also clears `transitions_paused` so starting is one step (prod-applicable: bootstrapping unpauses rotation) | 2026-06-02 | 5b1fd17 | [260602-dpm-bootstrap-ux-debug-cycle-seconds-anchors](./quick/260602-dpm-bootstrap-ux-debug-cycle-seconds-anchors/) |
| 260602-iuz | Reroll the CURRENT (active) cycle: extend `/tournament-reroll` with a `cycle` target (default `upcoming`, existing path byte-for-byte unchanged); `current` wipes the active cycle's submissions scoped by `cycle_id` (`delete_cycle_completions`), swaps to a new eligible map (reuses `fetch_eligible_maps`/LRU), recreates `status='active'` on the SAME edition so the deadline/window is preserved (timer never reset), announces via the existing `api.tournament.rollover` event. Mod/Sensei-gated. | 2026-06-02 | 51afde7 | [260602-iuz-add-ability-to-reroll-the-current-active](./quick/260602-iuz-add-ability-to-reroll-the-current-active/) |
| 260602-ld2 | Rewrite tournament-frontend-spec.md to be factual/current as of migration 0025 and simpler: framed FE as public read-only display + admin dashboard (submission/verify happen via Discord, not web); removed nonexistent `POST /cycles/{id}/submit`; cadence shown as global `config.cadence` (not per-category); documented the Edition timing entity + `GET /editions/active` with stored `ends_at` (dropped client-side derivation); added `reroll-active`/`bootstrap`/`publish-results`/`pause`/`debug-cycle-length` endpoints + `tournaments:verify` scope. Doc-only. | 2026-06-02 | 3ecd817 | [260602-ld2-rewrite-tournament-frontend-spec-md-to-b](./quick/260602-ld2-rewrite-tournament-frontend-spec-md-to-b/) |
| 260603-mla | Add boundary-streak cohorts to `scripts/seed_tournament_fake_data.sql`: 9 disjoint non-regular users sliced from one random draw, pinned to consecutive trailing edition runs of 2/3/5 (excluded from filler selection) so the unchanged gaps-and-islands derivation lands them on current_streak 2/3/5 — exercising the `streak_xp` thresholds (3 and 5) that the old bimodal {1, 26} distribution never hit. Debug-seed only — script left untracked per its DO-NOT-COMMIT banner; only planning docs committed. | 2026-06-03 | 41ffd64 | [260603-mla-add-boundary-streak-cohorts-to-tournamen](./quick/260603-mla-add-boundary-streak-cohorts-to-tournamen/) |
| 260605-gjy | Fix start-only rollover announcement: the `elif event.started` branch in `_on_edition_rollover` now leads with `# 🏆 New Tournament!` instead of `Tournament Ended!` — the start-only case (out-of-hiatus or never-started, `has_ended` False) had nothing end, so it no longer announces a non-existent prior tournament. Normal (results+started) and into-hiatus (results-only) branches keep their `Tournament Ended!` framing unchanged. Locked with assertions in the three existing rollover handler tests. | 2026-06-05 | 07f4745 | [260605-gjy-start-only-rollover-title](./quick/260605-gjy-start-only-rollover-title/) |
| 260607-oqy | Add a pingable tournament announcement role: new `mentionable.tournament_announcements` config field (struct + dev/prod TOML, `0` sentinel placeholder for maintainer-supplied IDs); both public announcement cards (`_on_edition_rollover`, `_on_edition_results`) prepend a `<@&id>` ping via shared `_tournament_ping()` helper with role allow-listed in `AllowedMentions`; self-assignable "Tournament Announcements" 🏆 toggle added to the `#role-react` view (`ServerRoleSelectView`), sourced from the same config field. Every touch point guards the `0` sentinel (no broken `<@&0>`, no crash-on-click button). | 2026-06-07 | 43e0904 | [260607-oqy-add-a-role-ping-to-tournament-announceme](./quick/260607-oqy-add-a-role-ping-to-tournament-announceme/) |
| 260608-ntz | Add an API route to remove a suspicious flag: symmetric `DELETE /completions/suspicious` mirroring the add route across all four layers (SDK `SuspiciousCompletionDeleteRequest`, repo `delete_suspicious_flag_by_message` reusing the insert's message/verification CTE, service `remove_suspicious_flags`, controller handler with the same 400 identifier guard + `status_code=200`) plus a bot `remove_suspicious_flags` client. Removing a non-existent flag returns 200 count 0. Fixes #50. | 2026-06-08 | 66c0b11 | [260608-ntz-add-an-api-route-to-remove-a-suspicious-](./quick/260608-ntz-add-an-api-route-to-remove-a-suspicious-/) |
| 260612-oqg | Fix skill-score leaderboard cold-start: `skill.snapshot` (created empty by migration 0027) is now auto-populated on API startup. New `SkillRepository.snapshot_is_empty()` (`NOT EXISTS` probe); `skill_nightly_rebuild_poller` in `app.py` runs `recompute_all()` ONCE after a 5s db_pool-warmup sleep when the snapshot is empty, reusing the exact existing `provide_skill_*`/`recompute_all` path (D-04, no forked logic) before the unchanged nightly 04:00 UTC loop. Broad-except + `log.exception` + clean cancel/await teardown preserved; populated-snapshot restarts skip the redundant rebuild. Verified live: cold boot auto-filled 261 rows in ~7s, leaderboard `sort_column=skill_score&sort_direction=desc` returns descending non-zero scores with `skill_rank` unchanged, restart-with-populated-snapshot is clean. | 2026-06-12 | 07467e1 | [260612-oqg-fix-skill-score-leaderboard-cold-start-p](./quick/260612-oqg-fix-skill-score-leaderboard-cold-start-p/) |
| 260612-u82 | Add `PATCH /api/v3/skill/tiers` admin endpoint to tune the tier `percentiles` (the only tunable in the `260612-pyo` tier system). Symmetric with `PATCH /skill/config` (weights): same `skill:admin` sentinel scope (no new scope). New SDK `SkillTiersUpdateRequest` (`percentiles: list[float]`), `InvalidPercentilesError` domain exception (→ HTTP 400, mirroring `InvalidGammaError`), `SkillRepository.update_percentiles` (positional `float8[]` bind), and `SkillService.update_tier_config` which validates (**exactly 6**, all strictly in `(0,1)`, **strictly increasing**) before any write, then persists percentiles and re-derives `boundaries` via the existing `compute_tier_boundaries` on a single transaction connection — NOT a full `recompute_all` (scores unchanged). Invalid input → 400, nothing persisted. `compute_tier_boundaries` SQL, scorer math, `skill.weight_config`, and the `skill_rank` CASE byte-for-byte unchanged. `just lint-api` clean; 30 skill tests pass (new PATCH happy-path, validation-rejection, and `skill:admin` auth-gate tests). | 2026-06-12 | 059e983 | [260612-u82-add-a-patch-api-v3-skill-tiers-endpoint-](./quick/260612-u82-add-a-patch-api-v3-skill-tiers-endpoint-/) |
| 260612-pyo | Add a percentile-based skill TIER system (display-only icon ranks) on top of the Phase-13 `skill_score`, fully separate from the Ninja..God `skill_rank` and the scoring math (both byte-for-byte unchanged). Migration `0028_skill_tier_config.sql` adds single-row `skill.tier_config` (`boundaries float8[]` default `'{}'`, `percentiles float8[]` seeded `[0.50,0.75,0.90,0.97,0.99,0.995]`, `computed_at`). `SkillRepository.compute_tier_boundaries` derives 6 cut-points via `percentile_cont WITHIN GROUP (ORDER BY skill_score)` over `skill_score>0` rows and is called inside the single `_do_recompute`/`recompute_all` path (D-04, not forked) — **flicker decision: boundaries recompute on every snapshot rebuild** (display tier can shift as the field moves; gateable to nightly later without schema change). Tier assigned via `width_bucket(skill_score, boundaries)+1` → 1..7; `skill_score=0`/no row → tier 0 Unranked; population-floor guard (<20 non-zero → empty boundaries → everyone Unranked). `tier`+`percentile` added to `SkillSummaryResponse` and `CommunityLeaderboardResponse` (+ leaderboard query, no `tier` in `sort_column`); new public `GET /api/v3/skill/tiers` returns boundaries+percentiles+computed_at. No hardcoded cutoffs (seeded percentile array is the only tunable), no new auth scope. `just lint-api` clean; 22 skill tests pass (new `TestSkillTiers`: assignment, Unranked/0, monotonicity, population-floor). | 2026-06-12 | b4a3bee | [260612-pyo-add-a-percentile-based-skill-tier-system](./quick/260612-pyo-add-a-percentile-based-skill-tier-system/) |
| 260612-vvm | Exclude `.planning` from local/editor Ruff + BasedPyright runs: added `".planning"` to `[tool.ruff].extend-exclude` and `[tool.basedpyright].exclude` in `pyproject.toml`. CI `lint.yml` already excluded it via explicit path args, so no workflow change. Config-only. | 2026-06-13 | 11faf57 | [260612-vvm-add-planning-to-ruff-and-basedpyright-ex](./quick/260612-vvm-add-planning-to-ruff-and-basedpyright-ex/) |
| 260612-vtt | Expand the skill TIER system from 7→8 named tiers plus Unranked, add string tier names, and rename leaderboard columns (percentile derivation + scorer byte-for-byte unchanged). Migration `0028` (edit-in-place) now seeds **7** strictly-increasing percentiles `[0.50,0.70,0.85,0.93,0.97,0.99,0.995]` so `width_bucket+1` mints integer tiers **1..8** (tier 0 = Unranked; zero score / empty boundaries). Single source-of-truth `SKILL_TIER_NAMES` (0=Unranked,1=Bronze,2=Silver,3=Gold,4=Emerald,5=Diamond,6=Ascendant,7=Elite,8=Champion) + `skill_tier_name()` helper added to `libs/sdk/skill.py`, reused by both the community leaderboard service and the skill summary path. New `skill_tier_name` field exposed on `SkillSummaryResponse` and `CommunityLeaderboardResponse`. Leaderboard columns renamed `tier`→`skill_tier`, `percentile`→`skill_percentile` (SQL aliases + struct; `skill_score` unchanged). Validation bumped to **exactly 7** (`_TIER_PERCENTILE_COUNT`, `InvalidPercentilesError`, SDK docstrings). Tests updated for 8 tiers, Unranked-at-0, renamed columns, name mapping. `just lint-sdk`/`lint-api` clean; full `just test-api` green. | 2026-06-13 | b0a0b0e | [260612-vtt-expand-the-skill-score-tier-system-from-](./quick/260612-vtt-expand-the-skill-score-tier-system-from-/) |
| 260613-rh2 | Mirror the four leaderboard skill fields onto the per-user rank card endpoint (`GET /api/v3/users/{user_id}/rank-card/`): `skill_score`, `skill_tier`, `skill_percentile`, `skill_tier_name` added to `RankCardResponse` (SDK, matching `CommunityLeaderboardResponse` names/types). New `RankCardRepository.fetch_skill_summary` ports the leaderboard's `skill.snapshot` + `skill.tier_config` projection to a single user, anchored on `core.users` so a snapshot-less user yields `0.0/0/0.0`; `rank_card_service` fetches it in the existing acquire block and name-maps the tier via the SDK `skill_tier_name()` single source of truth. Integration tests cover field presence/types + zero-eligible → `Unranked`. `just lint-sdk`/`lint-api` clean; `pytest -k GetRankCard` 4 passed. | 2026-06-14 | e1757cc | [260613-rh2-add-skill-score-column-to-get-rank-card-](./quick/260613-rh2-add-skill-score-column-to-get-rank-card-/) |
| 260629-btl | Add a `map_id` filter to the maps search endpoint (`GET /api/v3/maps`), mirroring the existing `code` filter exactly: locks to one map by integer primary key and bypasses CTE-based filters (mechanics/restrictions/tags/creators/quality/medals/completions) unless `force_filters` is set. `map_id: int \| None` field on `MapSearchFilters`; `_build_ctes` guard extended to `(code or map_id) and not force_filters`; `query.where_eq("m.id", ...)` clause; `map_id` query param threaded through the API route and the bot `get_maps` client. TDD: new `test_build_query_with_map_id` pins the m.id clause, arg binding, CTE bypass, and `force_filters` override. `just lint-api`/`just lint-bot` clean; full `just test-api` green (1951 passed). | 2026-06-29 | da3e7c2 | [260629-btl-add-map-id-filter-to-maps-search-endpoin](./quick/260629-btl-add-map-id-filter-to-maps-search-endpoin/) |
| 260629-caz | Add `GET /api/v3/store/admin/quests` (scope `store:admin`) — a list-all endpoint for the global quest pool, turning the Global-quests sub-tab into a real pool browser/editor (previously globals were only reachable by inspecting a user's rotation). Bare JSON array, no pagination (~19 seeded rows); optional filters `is_active`, `difficulty`, `q` (case-insensitive name `ILIKE`); locked to `quest_type = 'global'` (bounties have no pool row and stay reachable via the user-progress flow). Four layers: `QuestPoolResponse` SDK struct (id/name/description/quest_type/difficulty/coin_reward/xp_reward/requirements/is_active/created_at), `StoreRepository.get_all_quests` (dynamic WHERE over bound `$N` params), `StoreService.get_all_quests` (`msgspec.convert`), `list_quests` route handler. TDD: new `TestGetAllQuests` repository tests (global-only count, difficulty filter, is_active filter, case-insensitive name search). No bot client (store admin endpoints are web-dashboard-only). `just lint-api`/`just lint-sdk` clean; `pytest -m domain_store` 81 passed. | 2026-06-29 | b0054b3 | [260629-caz-add-get-store-admin-quests-list-all-endp](./quick/260629-caz-add-get-store-admin-quests-list-all-endp/) |
| 260813-fast | Scope the two map-name read routes to `maps:read` (`GET /utilities/autocomplete/names`, `GET /utilities/map-names`): both declared no `required_scopes`, which under `scope_guard` means superuser-only, so a non-superuser key (e.g. a `content:admin` map manager created via `POST /content/maps`) could add maps but never list them. Strictly permissive — superusers already bypassed the guard, so no existing caller changes. `just lint-api` clean; `tests/integration/test_autocomplete_integration.py` 24 passed (default test key is superuser). Executed via `/gsd:fast` — no quick-task directory. | 2026-08-13 | 428ab58 | — |

## Blockers/Concerns

- `ROADMAP.md`/`STATE.md` were missing locally (gitignored, never persisted); reconstructed 2026-06-01 to unblock GSD tooling.
- PROJECT.md originally listed manual cycle transitions as Out of Scope; quick-task work intentionally amends that for bootstrap + test tooling only.

## Accumulated Context

### Phase 15 Progress

- **15-05 autonomous tasks complete — human-verify pending (2026-06-25):** Bot DB-fed
  `MapNameSelect` (Wave 4, `depends_on: [15-04]`) — the bot consumer of the
  `GET /utilities/map-names` endpoint. **Task 1 (`63092a9`):** added
  `api_service.get_all_map_names() -> Response[list[str]]` — a PLAIN `def` returning
  `self._request(Route("GET", "/utilities/map-names"), response_model=list[str])`,
  mirroring the sync-def-returns-coroutine shape of `get_autocomplete_map_names` (callers
  `await`); REQ-09 unit test pins the Route + `response_model` (mocks `_request`, no live
  HTTP). **Task 2 (`7790327`):** DB-fed `MapNameSelect.__init__(current, all_maps, page=0)`
  — `list(get_args(OverwatchMap))` (now `()` post-15-01) replaced by an injected
  `all_maps: list[str]` = `sorted(all_maps)`; slice/`total_pages`/`SelectOption` math
  **byte-for-byte** (Spike 008). The full list is fetched ONCE in the async callback and
  threaded `MapEditWizardView.__init__ -> self._all_maps -> rebuild() -> MapNameSelect`
  at BOTH sites: `moderator.py` `/map edit` (`is_mod=True`) + `map_editor.py`
  `/map edit-request` (`is_mod=False`), each `await get_all_map_names()`; never awaited
  inside the sync `ui.Select.__init__`. `get_args(MapCategory)`/`Mechanics`/`Restrictions`/
  `Tags` untouched; `OverwatchMap` import KEPT (still the `current` annotation/`cast`,
  `=str`). **Task 3 (`8371bdd`):** REQ-10 pagination unit test (63-name DB-fed list:
  page-0 first 25 sorted, last-page remainder 13, `total_pages == ceil(n/25)`, `current`
  default, empty-list -> 0/0 no crash). **Bot test harness note:** bot has NO
  conftest/harness; both tests are SELF-CONTAINED (mocks/synthetic + in-file `sys.path`
  bootstrap of the bot root) and are NOT run by `just test-api` — verify via
  `cd apps/bot && uv run pytest tests/test_api_service.py tests/test_map_name_select.py -x`
  (8 passed). `just lint-bot` clean (0 pyright). No deviations. **Task 4 is a
  `checkpoint:human-verify` — NOT auto-passed:** the live discord.py UI has no test
  harness, so "a new map added via `POST /api/v3/content/maps` appears in the `/map edit`
  Map-Name dropdown with no bot restart, paginating 25/page" must be verified manually
  (steps in `15-05-SUMMARY.md`). **Phase 15: code/tests done across all 5 plans; awaiting
  the 15-05 human-verify approval.**

- **15-04 complete (2026-06-25):** Dynamic map management HTTP surface (Wave 3,
  `depends_on: [15-03]`) — the reachable API. **Task 1 (`2457922`):** new sibling
  `MapContentController(path=/content)` in `routes/v3/content.py` (NOT an extension of
  `MovementTechController` at `/content/movement-tech`, which would resolve the wrong
  URL) so `@post("/maps")` lands at EXACTLY `POST /api/v3/content/maps` (D-01),
  auto-discovered by `routes/v3/__init__.py`. `create_map` decodes a mixed-multipart
  `MapCreateMultipart{name: str, banner: UploadFile}` via `Body(MULTI_PART)`, is gated by
  `opt={"required_scopes": {"content:admin"}}` (T-15-10), caps the body at
  `request_max_body_size=1024*1024*25` (T-15-11), reads `await data.banner.read()`, calls
  `MapContentService.create_map`, and returns `MapCreateResponse{name, inserted}` (201).
  Re-post of an existing name → 201 `inserted: false` + banner overwrite at the same
  stripped key (D-03 replace-banner, REQ-04). DI wires `provide_map_content_service` +
  `provide_map_content_repository` + `provide_image_storage_service`; `from app import app`
  route introspection confirms registration (the DI-graph assertion deferred from 15-03).
  **Task 2 (`4a7f2a9`):** `AutocompleteController.list_all_map_names`
  (`GET /api/v3/utilities/map-names` → `list[str]`, full list, no search/limit, D-02/REQ-08)

  + `AutocompleteRepository.fetch_all_map_names` (`SELECT name FROM maps.names ORDER BY
  name`); the search-required `/autocomplete/names` route is byte-unchanged. **Task 3
  (`22eebd4`):** `test_map_content_integration.py` (create_map REQ-03, replace_banner REQ-04
  same-stripped-key overwrite, appears_everywhere REQ-15 = full-list + `core.maps` FK
  acceptance, empty-name 422, auth gate) + `test_autocomplete_integration.py::TestListAllMapNames`
  (map_names full-list REQ-08, no-search contrast, auth); the image service is stubbed
  (monkeypatch `__init__` + `upload_map_banner`) so the suite needs no MinIO/S3. **Deviations
  (2 auto-fixed, both Rule 3 blocking):** (1) promoted `ImageStorageService` out of
  `TYPE_CHECKING` in `map_content_service.py` — Litestar evaluates the 15-03 provider's
  `image_svc: ImageStorageService` hint at registration, so the name had to be runtime-resolvable
  or the whole app failed to construct (`NameError`); (2) stubbed `ImageStorageService.__init__`
  in tests, not just `upload_map_banner`, because `__init__` builds a boto3 client that raises
  `Invalid endpoint` without an S3 config. Verified: `just lint-api` clean (0 pyright errors),
  targeted `-k "create_map or replace_banner or map_names or appears_everywhere"` 5 passed,
  full `just test-api` green (49 passed, testmon-selected). **15-05 (bot DB-fed `MapNameSelect`

  + `api_service.get_all_map_names()`) consumes the `GET /utilities/map-names` endpoint this
  plan shipped.** **Phase 15: 4/5 plans complete.**

- **15-03 complete (2026-06-25):** Map content service + storage layer (Wave 2,
  `depends_on: [15-01, 15-02]`). The service-layer runtime gate replacing the lost
  `OverwatchMap` Literal. **Task 1 (`b397311`→`63b7da3`):** `ImageStorageService.upload_map_banner`
  keys the object at `assets/map_banners/{stripped}.png`, **byte-matching `get_map_banner()`**
  (`re.sub(r"[^a-zA-Z0-9]","",name).lower().strip().replace(" ","")`), extension ALWAYS `.png`
  regardless of source content-type (read path hardcodes it); CacheControl `max-age=3600,
  must-revalidate` (replaceable, Open Q1) (D-05/REQ-07). **Task 2 (`5b1c13b`→`6856b7a`):**
  `MapContentRepository` — `insert_map_name` (`INSERT ... ON CONFLICT DO NOTHING RETURNING name`
  → `{name, inserted}`, idempotent re-insert returns `inserted=False`, 201+flag not 409, Open Q2)

  + `fetch_all_map_names` (sorted); `provide_map_content_repository`. **Task 3 (`0e7eb57`→`90d94e3`):**
  `MapContentService.create_map` — empty guard 422 (REQ-05) → stripped-key collision guard 422
  naming the existing map (REQ-06/D-07) → banner upload (REQ-07) → single-statement idempotent
  insert, **all fallible non-DB work before the insert, no txn wrap (RESEARCH Pitfall 1)**;
  `validate_map_name` (REQ-02, consumer-side) returns known or 422s unknown with a
  `difflib.get_close_matches` "did you mean"; `provide_map_content_service` **declares**
  `image_svc` dep (controller wires it in 15-04). **Deviations (2 auto-fixed):** (Rule 3) real-DB
  repository tests relocated to `tests/repository/maps/test_map_content_repository.py` —
  `tests/services/conftest.py` no-ops `setup_test_db` so real-DB tests can't run there; service
  tests use a mocked repo + mocked image svc. (Rule 1) plan's accent-collision premise corrected:
  `get_map_banner` **removes** accents (`â`→∅), not folds, so `Château Guillard`→`chteauguillard`
  ≠ `Chateau Guillard`→`chateauguillard` — NOT a collision; real collisions are punctuation/
  whitespace that strip identically (`King's Row`/`Kings Row`, `Lijiang Tower`/`Lijiang  Tower`).
  Verified: `just lint-api` clean (0 pyright errors), `pytest -k "validate_map_name or empty_name
  or collision or upload_map_banner or insert or fetch_all"` **48 passed**, full suite (no testmon)
  **1942 passed / 2 skipped / 2 xfailed / 0 failures**. **15-04 must wire `Provide(provide_image_storage_service)`

  + `Provide(provide_map_content_repository)` in `MapContentController.dependencies`; the
  `from app import app` DI-graph resolution is asserted there.** **Phase 15: 3/5 plans complete.**

- **15-02 complete (2026-06-26):** Map-names durability & integrity (Wave 1).
  **Task 1 (`f84d193`):** rewrote the `maps.names` seed in `0001_init.sql` from 63
  plain `INSERT`s into ONE `INSERT ... VALUES (...) ON CONFLICT DO NOTHING;` block of
  all **70** reconciled names (63 live + 7 phantom); machine-verified the 70 equal
  `(old 63) ∪ (7 phantom)` — exact, no drift. Fixes the latent duplicate-PK replay bug
  and gives fresh-bootstrap parity (REQ-12/D-09/D-08). No `banner_url` column (D-06).
  **Task 2 (`d040e2e`):** `0032_dynamic_map_management.sql` — load-bearing sequence:
  reconcile 7 phantoms `ON CONFLICT` → `DO $$ ... RAISE EXCEPTION` orphan pre-flight
  (fails LOUD, never silently) → `ALTER TABLE core.maps ADD CONSTRAINT
  maps_map_name_names_fk FOREIGN KEY (map_name) REFERENCES maps.names (name) ON UPDATE
  CASCADE`, mirroring `maps.mastery` (REQ-11/D-11). Plus `scripts/export_map_names_seed.py`
  — standalone on-demand `asyncpg` seed export, unreferenced by `apps/`, off the request
  path, not in the nightly backup (REQ-14/D-10). **Task 3 (`46ca360`):** 5 schema tests
  (`test_map_management_schema.py`): `phantom_maps`, `seed_idempotent`, and three
  `map_name_fk` (FK exists + orphan→`ForeignKeyViolationError` + known-name succeeds);
  the 15-VALIDATION `-k` filters resolve. **Deviations (3 auto-fixed):** (Rule 3) made
  `0003_stadium_maps_1.sql` idempotent — it pre-seeded 6 phantoms with plain INSERTs and
  the new 0001 seed made a fresh apply raise duplicate-PK at 0003, blocking all migrations;
  (Rule 1) seeded the fictional `map_name`s into `maps.names` before the two `core.maps`
  inserts in `test_tournaments_schema.py` that the new FK correctly rejected (4 tests);
  (Rule 1) `confupdtype == b'c'` (asyncpg returns Postgres `"char"` as a byte). Verified:
  `just lint-api` clean, full API suite `pytest -n 4 --no-testmon` **1921 passed / 2
  skipped / 2 xfailed / 0 failures**; `grep -c banner_url 0001_init.sql` == 0. **The FK
  backstops the runtime `maps.names` validation 15-03 adds to replace the lost enum gate.**
  **Phase 15: 2/5 plans complete.**

- **15-01 complete (2026-06-26):** Dropped the `OverwatchMap` Literal (Wave 1 root,
  `depends_on: []`). **Task 1 (`f8e7b24`):** replaced the closed 70-entry
  `OverwatchMap = Literal[...]` in `libs/sdk/.../maps.py` with a single
  `OverwatchMap = str` (REQ-01 / D-04 request-side) — the map-name validation gate is
  off the msgspec decode boundary; msgspec still enforces presence/type (missing/non-string
  name → 400). `OverwatchMap` is kept defined + in `__all__`, so the ~27 consumers compile
  untouched (Assumption A1). `MapCategory`/`Mechanics`/`Restrictions`/`Tags`/`DifficultyAll`
  stay strict Literals (`get_args(MapCategory)` still len 3). **Task 2 (`56e5ce5`):** repaired
  all **9** `get_args(OverwatchMap)` fixture sites (`conftest.py` + 8 test files) — after the
  flip `get_args(str)` returns `()` and `fake.random_element([])` raises, blocking the whole
  suite, so the two changes are inseparable. Each site now draws from a module-level
  `_SEED_MAP_NAMES = ["Hanamura","Busan","Ilios","Nepal","Oasis"]` (real `maps.names`
  FK targets confirmed in `0001_init.sql`); dropped the now-unused `OverwatchMap` imports,
  kept `get_args` for `MapCategory`/`PlaytestStatus`; removed the dead factory imports in
  `conftest.py` (it already used string literals). The RESEARCH "14 files" was an overcount —
  live grep confirmed 8 test files + conftest = 9 sites, zero under `apps/bot/tests/`.
  **The 70 verbatim map names are captured in `15-01-SUMMARY.md` for plan 15-02's seed rewrite**
  (incl. the 7 phantom maps). Verified: `just lint-sdk` clean, `just lint-api` clean, full
  `just test-api` **1722 passed / 2 skipped / 2 xfailed / 0 failures**; zero
  `get_args(OverwatchMap)` references remain (backstop grep returns 0 files — the explanatory
  comments were reworded to avoid the literal pattern). No deviations.
  **Dependency note (T-15-01):** this plan ONLY relaxes the type — the lost enum gate MUST be
  replaced by a service-layer runtime check against `maps.names` (15-03, REQ-02) + the
  `core.maps.map_name` FK backstop (15-02, REQ-11) before the surface ships. **Phase 15: 1/5
  plans complete.**

### Phase 14 Progress

- **14-05 complete (2026-06-16):** Dashboard routes + end-to-end tests (Wave 4, the
  reachable-API surface + the phase's e2e proof). **Phase 14 complete (5/5 plans).**
  Added three PUBLIC GET routes to `SkillController` (`routes/v3/skill.py`, no `opt` —
  matching the existing `/skill` reads): `users/{id}/history?window=` (windowed
  points+summary), `users/{id}/changes?window=&limit=&offset=` (newest-first feed,
  `limit` ge=1 le=100, `offset` ge=0 mirrored from tournaments), and
  `users/{id}/changes/{change_id}` (drill-down → service `None` → `HTTPException(404)`,
  T-14-06 IDOR — 404 not 403). `window` is a module-level `Window =
  Literal["7d","30d","90d","1y","all"]` Parameter (msgspec auto-4xx on unknown,
  T-14-13; never interpolated into SQL). `PATCH /config` recompute now tagged
  `TriggerDescriptor(cause_category="SYSTEM")` (D-09); `PATCH /tiers` untouched (A1).
  New `tests/integration/test_skill_dashboard.py` (14 tests, Req 1-7): ≥2
  distinct-`captured_at` history rows after two recomputes (Req 1); known-series
  best/lowest/average + point/percent change, invalid window 4xx, empty user 200
  empty/zero (Req 3); descending feed + `limit` bound + window respected + empty `[]`
  (Req 4); per-row `Σ impact + other_factors == delta` within 1e-6 + foreign/unknown
  change_id 404 (Req 5); five-window in-range filtering + `all` full + unknown 4xx
  (Req 6); empty user 200/[]/404 across all three endpoints, never 500 (Req 7); actor
  PLAYER_ACTION vs bystander MAP_ENVIRONMENT + SYSTEM coalesced (Req 2 e2e). Verified:
  `pytest test_skill_dashboard.py` → 14 passed; `test_skill.py` → 12 passed;
  `test_skill_scorer.py test_skill_service.py -m domain_skill` → 19 passed (no
  regression); `just lint-api` + `just lint-sdk` clean. **Deviations (2, both Rule-1
  self-introduced test bugs fixed pre-commit):** the conservation test read a race-prone
  `feed[0]` (sibling tests' global recompute appends rows on the shared DB) — rewritten
  to assert the per-row invariant on ALL of a user's change rows + single map (the seed
  factory's `map_name='Hanamura'` collapses multi-map diffs); and a wrong hand-computed
  average literal (`25` → `(10+30+40)/3`). Commits `6d4b41b` (Task 1) / `acc138d`
  (Task 2).

- **14-04 complete (2026-06-16):** Capture wiring + cause policy + read methods — the
  core of Phase 14 (Wave 3). **Task 1 was pre-committed (`251b276`)** before this
  executor ran: the capture wiring in `_do_recompute` (reads `fetch_all_snapshots`
  BEFORE `replace_snapshot` truncates — Pitfall 1), the `TriggerDescriptor` dataclass,
  the module-scope `_RecomputeGuard.pending` accumulator (drained INSIDE the rerun
  loop — Pitfall 2), `_resolve_cause_policy`, and the `_build_diff` conservation join.
  This executor verified Task 1 then did **Task 2 + Task 3**. **Task 2 (`8b147c3`):**
  `events/skill.py` builds a `TriggerDescriptor(cause_category, actor_user_id)` and
  threads it into `recompute_all` (cause from the typed accumulator, never `reason`-string
  parsing — T-14-10); `_emit_skill_recompute` gains `cause_category` + `actor_user_id`;
  the five emit sites pass the completion owner as `PLAYER_ACTION` (verify/un-verify →
  `completion_info["user_id"]`, moderate → `user_id`, flag/unflag → A4 owner lookup via
  `self._completions_repo.fetch_completion_owner_by_message`, NO cross-service private
  access); `update_tier_config` (PATCH /skill/tiers) left untouched per A1. Three read
  methods added: `get_user_history` (window→since, summary anchored on earliest record,
  empty→`points=[]`+zero summary), `get_user_changes` (paginated feed, empty→`[]`),
  `get_user_change_detail` (ownership→None→404, sort `diff.maps` by `abs(impact)` desc,
  top `_TOP_N=5`→`main_causes`, residual tail→`other_factors`, conservation exact).
  **Task 3 (`9fdfbed`):** four service tests lock the actor/bystander cause split,
  coalesced-burst→SYSTEM promotion, prev-before-truncate `previous_score`, and
  `Σ impact ≈ delta` within 1e-6; `_reset_guard` already cleared `pending` (Task 1).
  Verified: `pytest tests/services/test_skill_service.py tests/services/test_skill_scorer.py`
  → 19 passed; `tests/integration/test_skill.py` → 15 passed (no Phase 13 regression);
  scorer byte-for-byte unchanged (git diff); `just lint-api` clean. One self-introduced
  Rule-1 fix pre-commit (an undefined `points_src` helper, corrected to direct iteration).
  Commits `8b147c3` (Task 2) / `9fdfbed` (Task 3). **Phase 14: 4/5 plans complete.**

- **14-03 complete (2026-06-16):** Skill dashboard repository methods (Wave 2,
  additive — Phase 13 scorer/snapshot methods byte-for-byte untouched). Added six
  methods to `SkillRepository` (`apps/api/repository/skill_repository.py`) and one
  owner lookup to `CompletionsRepository`, all `*, conn: Connection | None = None`,
  positional-param-only, `just lint-api` clean. **Capture layer (D-05):**
  `fetch_all_snapshots` is ONE `SELECT user_id, skill_score, breakdown FROM
  skill.snapshot` returning `{user_id: {skill_score, breakdown}}` — callable BEFORE
  `replace_snapshot` TRUNCATEs (Pitfall 1) and single-round-trip (Pitfall 3);
  `bulk_insert_history` / `bulk_insert_changes` mirror `replace_snapshot`'s
  `executemany` + Pool-vs-Connection fork but are **append-only (NO TRUNCATE,
  empty-list-safe)**, and `diff` rides the jsonb codec as a raw Python dict (no
  `json.dumps`). **Read layer:** `fetch_history` (`captured_at >= $2 ORDER BY ASC`),
  `fetch_changes` (newest-first `ORDER BY captured_at DESC LIMIT $3 OFFSET $4`,
  **SELECT deliberately omits the heavy `diff` jsonb** — Warning 4; feed never renders
  the per-map array), and `fetch_change` — the ONLY method that SELECTs `diff` — with
  the IDOR ownership predicate `WHERE change_id=$1 AND user_id=$2` baked into the SQL
  (T-14-06: foreign id → None → route 404, not 403). **A4 resolution:**
  `CompletionsRepository.fetch_completion_owner_by_message` SELECTs `user_id FROM
  core.completions` using the identical message_id/verification_id model as the
  suspicious-flag methods in the same file — lives on the repo that owns
  `core.completions` so 14-04's completions service calls it via `self._completions_repo`
  (no cross-service private access). Verified: both `<verify>` one-liners pass
  (Task 2's checked SQL-scoped after a docstring false-positive — see deviation);
  `git diff` shows additions only (`replace_snapshot`/scorer/tier methods unchanged);
  `pytest tests/integration/test_skill.py` 15 passed (additive, no regression).
  **Deviation (Rule 1, plan-owned):** Task 2's verify one-liner `'diff' not in fc`
  false-positives on the `fetch_changes` docstring (which legitimately documents the
  Warning-4 omission); validated the real acceptance criterion via an AST docstring-strip
  showing the SQL omits `diff`, kept the load-bearing docstring. Commits `e32fb1a`
  (Task 1) / `58cb910` (Task 2). **Phase 14: 3/5 plans complete.**

- **14-02 complete (2026-06-16):** Skill dashboard wire contracts (interface-first,
  no DB/service dependency). Added seven new msgspec structs + the `CauseCategory`
  Literal to `libs/sdk/.../skill.py` and enriched `SkillRecomputeRequestedEvent` (D-10)
  so Waves 2-4 implement against fixed contracts. **SDK:** `CauseCategory =
  Literal["PLAYER_ACTION","MAP_ENVIRONMENT","SYSTEM"]` — the single SDK source for the
  closed set (the migration 0031 CHECK is the DB backstop); History (req 3)
  `SkillHistoryPoint`/`SkillHistoryExtremum` (`date: datetime | None` for the empty
  shape)/`SkillHistorySummary` (point_change/percent_change/best/lowest/average)/
  `SkillHistoryResponse` (user_id/points/summary); Feed (req 4) `SkillChangeFeedItem`
  (change_id/captured_at/delta/cause_category/description); Drill-down (req 5)
  `SkillChangeCause` (map/reason/impact)/`SkillChangeDetailResponse`
  (change_id/captured_at/previous_score/new_score/delta/percent_change/cause_category/
  main_causes/other_factors). All seven + `CauseCategory` in `__all__`; no Phase 13
  struct touched. **Event** (`apps/api/events/schemas.py`): added `cause_category: str =
  "SYSTEM"` (plain `str`, NOT the SDK Literal — keeps the API-side event module
  dependency-light; the service validates the closed set) + `actor_user_id: int | None =
  None`; `reason` kept first so existing `SkillRecomputeRequestedEvent(reason=...)` calls
  and the `events/skill.py` listener stay backward-compatible. Verified: structs
  round-trip (empty-points/zero-summary + main_causes/other_factors shapes), `cause_category="BOGUS"`
  raises `msgspec.ValidationError` (T-14-04 mitigated at decode), event constructs
  old-style + enriched; `just lint-sdk` + `just lint-api` clean (0 errors). No deviations.
  Commits `0501374` (Task 1) / `d3129e5` (Task 2). **Phase 14: 2/5 plans complete.**

- **14-01 complete (2026-06-16):** Migration `0031_skill_history.sql` — the
  forward-only data foundation for the skill dashboard. Two new `skill`-schema
  capture tables (D-01): a **lean** `skill.score_history` (`user_id bigint`,
  `captured_at timestamptz`, `skill_score double precision`; composite
  `PRIMARY KEY (user_id, captured_at)` covering every `/history` window read — no
  extra index) and a **rich** `skill.score_change` (`change_id bigserial PK`,
  `user_id`, `captured_at`, `previous_score`, `new_score`, `delta`,
  `cause_category text`, `reason text`, `diff jsonb DEFAULT '{}'`). `cause_category`
  is **text + CHECK** (`PLAYER_ACTION`/`MAP_ENVIRONMENT`/`SYSTEM`, T-14-01) — no
  Postgres enum, consistent with the skill-migration idiom. `diff` (D-04) stores the
  all-maps impact array round-tripped by the existing jsonb<->msgspec codec. Feed
  index `skill_score_change_user_captured_idx (user_id, captured_at DESC)` backs the
  newest-first `/changes` read. Forward-only: **no backfill INSERT, no pg_cron** (D-03;
  the nightly recompute is an app-side lifespan task); idempotent
  `CREATE SCHEMA/TABLE/INDEX IF NOT EXISTS` wrapped in `BEGIN;`/`COMMIT;`. Scorer/tier
  tables (`skill.snapshot`, `skill.weight_config`, `skill.tier_config`) untouched.
  Verified by the existing 4 `test_skill.py` integration tests passing — the migration
  applies cleanly at session start via `conftest.py:_apply_sql_dir`. **Deviation (Rule 1,
  plan-owned):** the plan's `<verify>` one-liner had an unsatisfiable CHECK assertion (it
  strips spaces from the SQL but not from its own search string), so the migration was
  validated against the actual whitespace-insensitive acceptance criterion instead (passes).
  Commit `5f4e29c`. **Phase 14: 2/5 plans complete.**

### Phase 13 Progress

- **13-06 complete (2026-06-12):** Skill freshness contract + leaderboard column —
  the riskiest integration point, closing the symmetric add/remove acceptance
  criteria. `completions_service.py` gains a `_emit_skill_recompute` helper
  (post-commit, fire-and-forget, guarded for the optional-request/event-driven case)
  that fires `request.app.emit("skill.recompute.requested", SkillRecomputeRequestedEvent(...),
  skill_service=skill_service)` from **all four D-02 state-change paths**:
  `verify_completion` emits in BOTH the verify (`data.verified=True`) and un-verify/reject
  (`False`) branches after `update_verification` commits, and `set_suspicious_flags` /
  `remove_suspicious_flags` — which previously took neither a `request` nor a
  `skill_service` — were threaded with both and emit post-commit (flag drops a user's
  contribution → score 0; un-flag restores it). The route handlers (verify + POST/DELETE
  suspicious) inject `request: Request` + `skill_service: SkillService`, and
  `provide_skill_service`/`provide_skill_repository` were added to
  `CompletionsController.dependencies` so the listener's `skill_service` arg resolves
  (5 `skill.recompute.requested` occurrences, ≥4 emit sites). The community leaderboard
  (`community_repository.fetch_community_leaderboard`) gained `LEFT JOIN skill.snapshot ss
  ON u.id = ss.user_id` + `coalesce(ss.skill_score, 0) AS skill_score` (D-07 zero-eligible
  ranked last) and `"skill_score"` (D-08) in the `sort_column` Literal — duplicated into
  the service + route Literals; it sorts via the existing plain-column branch (no CASE
  added) and `skill_rank` + its CASE are UNTOUCHED (SPEC req 6). New
  `tests/integration/test_skill.py` (10 tests, all passing) proves the full SPEC matrix:
  verify→raises / reject→restores within 1e-6 / flag→0 / unflag→restores; field relativity
  (a second player on the same map shifts after the field changes); `sort=skill_score`
  descending + paginated with `skill_rank` intact; zero-eligible player score 0 ranked last

  + `GET /skill/users/{id}` returns 0 / empty breakdown; PATCH 401 unauth / 401-403
  non-superuser / 200 superuser with scores changing; breakdown contributions sum to total.
  The test drives the deterministic snapshot via the shared `recompute_all` on its own pool
  (last writer, after a 0.1s settle yield) while still firing the real background emit via the
  HTTP endpoints — sidestepping the background-listener app-pool-teardown race (a logged,
  non-fatal listener error). `just lint-api` clean. No deviations. Commits `8222496` (Task 1)
  / `affd0ad` (Task 2) / `58df609` (Task 3). **Phase 13 complete (6/6 plans).**

- **13-05 complete (2026-06-12):** Skill HTTP surface + recompute machinery — the
  service becomes a reachable API. New `apps/api/routes/v3/skill.py` `SkillController`
  (`path="/skill"`, auto-registered): three typed GET reads (`/users/{id}` →
  `SkillSummaryResponse` with the D-07 zero-player rule, `/users/{id}/breakdown` → the
  D-06 per-map JSONB `list[SkillBreakdownRow]`, `/config` → `Weights`) plus a
  superuser-only `PATCH /config` (`opt={"required_scopes": {"skill:admin"}}` sentinel —
  superuser bypasses the reused `scope_guard`, everyone else 401/403; NO new scope
  minted) that runs `update_weights` then an immediate `recompute_all` (D-10), mapping
  `InvalidGammaError`→422 before any rebuild. New `apps/api/events/skill.py` —
  `@listener("skill.recompute.requested") handle_skill_recompute` running the single
  `recompute_all` (D-04), auto-registered by `events/__init__.py` discovery (6 listeners,
  no `__init__.py` edit); `SkillRecomputeRequestedEvent` (optional `reason` only, no
  required fields) added to `events/schemas.py`. In `app.py`, a new
  `skill_nightly_rebuild_poller` lifespan task (mirrors `tournament_outbox_poller`) is the
  D-03 durability backstop: sleeps to the next 04:00 UTC slot, builds the service via the
  existing `provide_skill_repository`/`provide_skill_service` DI from `_app.state`, runs the
  SAME `recompute_all` (D-04), CancelledError-safe, registered in `lifespan=[...]`. **No
  pg_cron added** — the scorer is Python, so the app-side scheduler is the chosen mechanism
  (PATTERNS flag resolved). `just lint-api` clean; `import app` succeeds. No deviations.
  Commits `e6e47af` (Task 1) / `7e8ca94` (Task 2) / `d712a42` (Task 3).

- **13-04 complete (2026-06-12):** SkillService — the scoring engine (heart of the
  phase). New `apps/api/services/skill_service.py` ports the spike's hybrid scorer
  (`score.py:44-106`) into module-level helpers over the SDK `Weights` struct:
  `_diff_weight` (`diff_base**(raw-1.5)` floor), `_map_score` (partial→`floor*partial_factor`
  only; video→floor × time/medal/WR multipliers with field-size shrink `field/(field+k)`),
  `_player_score` (`Σ sᵢ/iᵞ` over desc-sorted per-map scores), `_player_breakdown` (the D-06
  per-map JSONB array, keys mirror `SkillBreakdownRow`). **Proven equivalent to the spike
  within 1e-6 across all 261 real-data players** (`test_skill_scorer.py` loads
  `.planning/spikes/001…/skill_inputs.json` + imports the spike `score.py` as the oracle);
  plus partial<video and the gamma break-even dial. **No weight literal anywhere** in the
  service (SPEC req 5; grep clean). `recompute_all` is THE single rebuild routine (D-04 —
  event + nightly + PATCH): `fetch_weights`→`msgspec.convert(Weights)`→`fetch_skill_inputs`→
  group-by-user→score+breakdown→`replace_snapshot` (lean, D-07), wrapped in a **process-wide
  in-flight collapse guard** (`_RecomputeGuard`, lazy `asyncio.Lock` + rerun flag — module
  scope because DI builds a fresh service per request; D-05/T-13-08). Read methods honor the
  D-07 empty-player rule (`get_user_skill`→all-zero summary, `get_user_breakdown`→`[]`) and
  decode the D-06 JSONB breakdown; `update_weights` rejects `gamma<0.5` (`InvalidGammaError`,
  new `services/exceptions/skill.py`) before writing only the non-UNSET fields (PATCH→recompute
  stays in the route, D-10/13-05). `just lint-api` clean; 10 skill tests pass. Deviations: 2
  Rule-3 (blocking) test-infra fixes — corrected the equivalence-test inputs path to the
  `.planning/spikes/` location that exists + registered the `domain_skill` marker; registered
  the importlib-loaded spike module in `sys.modules` before exec so its `@dataclass` resolves.
  Commits `10e6586` (Task 1) / `017fafa` (Task 2).

- **13-03 complete (2026-06-12):** Skill repository (data-access layer). New
  `apps/api/repository/skill_repository.py` — the only place raw SQL for skill lives.
  `fetch_skill_inputs` ports the spike 4-CTE input query
  (`best → field → video_ranked → fully`) **verbatim** into a `SKILL_INPUT_QUERY` module
  constant, with every gotcha preserved: the `best` eligibility WHERE
  (`verified=TRUE AND legacy=FALSE AND archived=FALSE AND code IS NOT NULL`,
  `DISTINCT ON (user_id, map_id) ORDER BY time ASC`); a distinct `video_ranked` CTE
  (ranks only `completion = FALSE`) LEFT JOINed back instead of an invalid
  `rank() OVER (...) FILTER (...)`; `raw_difficulty::float8` (never the text tier) and
  `time_pct = percent_rank() ... ORDER BY time DESC` (1.0 = fastest, never raw time
  across maps); computed `medal`/`has_medal_thresholds`/`suspicious`. Suspicious rows are
  dropped in Python (`if not row["suspicious"]`, mirroring the spike harness) so the SQL
  stays a verbatim port. Plus `fetch_snapshot` (single lean row, breakdown rides the
  jsonb codec), `replace_snapshot` (atomic `TRUNCATE` + `executemany` bulk insert in one
  transaction via the `tags_repository` acquire-if-`Pool` pattern; empty-list-safe),
  `fetch_weights` (the single `weight_config` row — SPEC req 5 the only weight source),
  `update_weights` (allow-listed partial PATCH SET from a `_WEIGHT_COLUMNS` frozenset,
  T-13-07; empty update returns the current row), and `provide_skill_repository`.
  `just lint-api` clean (ruff + basedpyright 0 errors). No deviations. Commits `542c810`
  (Task 1) / `ab6b981` (Task 2).

- **13-02 complete (2026-06-12):** Skill SDK wire contracts (interface-first, no DB
  dependency). New `libs/sdk/.../skill.py` exports four msgspec structs: `Weights`
  (1:1 with the D-09 `skill.weight_config` row — `diff_base, gamma, time_bonus,
  shrink_k, wr_bonus, partial_factor, medal_gold/silver/bronze`, all `float`, all
  required, **no defaults** so SPEC req 5 "no hardcoded weights" holds — defaults live
  only in the 0027 seed); `SkillConfigUpdateRequest` (one `float | UnsetType = UNSET`
  per weight, PATCH partial-update semantics, mirrors the `content.py` UNSET pattern);
  `SkillSummaryResponse` (`user_id, skill_score, maps_cleared, video_clears,
  hardest_raw`); and `SkillBreakdownRow` (9 fields `map_name, difficulty, raw,
  fully_verified, medal: str | None, wr, raw_score, contribution, rank` — names mirror
  the spike `player_breakdown` keys `score.py:78-88` exactly so the stored D-06 JSONB
  array decodes straight into `list[SkillBreakdownRow]` via the jsonb<->msgspec codec).
  Registered the `skill` module in the SDK `__init__.py` re-export convention. Added a
  single non-optional `skill_score: float` to `CommunityLeaderboardResponse` adjacent to
  the **untouched** `skill_rank` label (non-optional because the leaderboard SQL
  `COALESCE(ss.skill_score, 0)` guarantees a value, D-07/D-08); docstring documents both,
  no existing field renamed/reordered. Plan verifies pass (weights round-trip with
  `.gamma==0.68`, missing key raises, `SkillConfigUpdateRequest()` round-trips all-UNSET,
  `SkillBreakdownRow` decodes with `medal=None`, both leaderboard fields present);
  `just lint-sdk` clean. No deviations. Commits `77985ef` (Task 1) / `1250506` (Task 2).

- **13-01 complete (2026-06-12):** Migration `0027_skill_score.sql` — the data
  foundation for the skill-score phase. Creates `CREATE SCHEMA IF NOT EXISTS skill`;
  a **lean** `skill.snapshot` cache (`user_id bigint PRIMARY KEY`, no FK — only
  players with ≥1 eligible run get a row, D-07; `skill_score`, `maps_cleared`,
  `video_clears`, `hardest_raw`, `breakdown jsonb DEFAULT '[]'` per-map array D-06,
  `computed_at`); and a single typed-column `skill.weight_config` row (one column per
  weight, D-09) with `CHECK (gamma >= 0.5)` (T-13-01 — the farm-enabling gamma=0 is
  unrepresentable). Seeded idempotently (`INSERT ... SELECT ... WHERE NOT EXISTS`) with
  the adopted defaults (diff_base=1.44, gamma=0.68, time_bonus=0.55, shrink_k=10.0,
  wr_bonus=0.10, partial_factor=0.60, medals 1.12/1.07/1.03). **No pg_cron block** —
  the scorer is Python (`SkillService`), so the nightly rebuild backstop is an app-side
  lifespan task in plan 13-05, NOT a SQL cron (D-03); omitting cron also keeps "applies
  cleanly on a fresh test DB" trivially true. Verified on a throwaway DB: both apply
  exit 0, tables resolve via `to_regclass`, seed count 1 (and stays 1 on re-apply),
  gamma=0.0 insert rejected, 0 `cron`/`lootbox`/`xp`/`skill_rank` references. No
  deviations. Commit `de2456d`.

### Phase 12.1 Progress

- **12.1-05 complete (2026-06-01):** Bot deferred-results handler + force-publish
  command (D-01/D-03/D-04/D-05) — the bot-side completion of the verification-aware
  flow. New `_on_edition_results` consumer (`@queue_consumer("api.tournament.results",
  struct_type=TournamentEditionResultsEvent, idempotent=True)`) posts the deferred
  results as a NEW separate Components-V2 card (D-04 — no edit-in-place, no stored
  message ids) and performs the HELD champion-role transfer (D-05) per result entry by
  reusing `_transfer_champion_role` verbatim (strip-all-then-grant, staggered,
  guild-leave-safe, vacant-on-None-winner); an empty/all-rejected edition posts a
  no-winner card and transfers nothing. `_on_edition_rollover` renders a `## 🏅 Results
  / Results pending verification…` placeholder when `results_pending=True` (empty
  `results` → transfer loop skips → previous champion KEEPS the role, D-01/D-05); the
  empty-event early-return guard was widened with `and not results_pending` so a
  hiatus+pending placeholder-only event still posts. New mod-gated
  `/tournament-publish-results` command (in `TournamentRerollCog`, copying
  `/tournament-reroll`): defer ephemeral → AUTHORITATIVE bot-side `is_mod` (mod or
  sensei) gate raising `UserFacingError` before any API call (T-12.1-14;
  `default_permissions(manage_guild=True)` is a UI hint) → `ConfirmationView` gate
  (abandon is irreversible) → `api_service.force_publish_tournament_results()`. New
  `api_service.force_publish_tournament_results` = PATCH `/tournaments/publish-results`
  → `JobStatusResponse` (the bot's ONLY DB path — bot never writes Postgres).
  Mention-injection mitigation reused verbatim (numeric `<@id>` only + AllowedMentions
  allow-list, ping in a TextDisplay, T-12.1-15). 8 new bot tests (5 handler + 3
  command); `just lint-bot` clean; TRUE full suite (`-n 4 --no-testmon`) **1839 passed
  / 2 skipped / 2 xfailed / 0 failures** (up from 1831). No deviations. Commits
  `c834ba5` (Task 1) / `8d43bfb` (Task 2). **Phase 12.1 complete (5/5 plans).**

- **12.1-04 complete (2026-06-01):** Poller drain state machine + force-publish
  (D-01/D-02/D-03/D-05/D-07) — the heart of the phase. `process_awaiting_results_editions`
  now runs INSIDE the existing publish-before-mark outbox transaction and implements
  the D-07 three-branch drain state machine per `awaiting_results` edition (locked
  `FOR UPDATE SKIP LOCKED`, `ends_at ASC`): first-tick-no-pending → combined
  `TournamentRolloverEvent(results_pending=False)` + grant + complete; first-tick-pending
  → start-only `TournamentRolloverEvent(results_pending=True)` (empty results → champion
  role held, D-05) + `start_announced`, no grants; later-tick-drained → write an
  `edition_results` outbox row (the SAME loop drains+publishes+grants it next tick at
  `tournament:results:{edition_id}`, Pitfall 3 at-least-once) + complete. The grant loop
  (`award_cycle_end` + `_reset_non_participant_streaks`) is reused VERBATIM inside the
  transaction (docstring 21-38 invariant intact); the deferred grant runs exactly once
  when the row drains (no double-grant). Force-publish (D-03): `force_publish_results`
  reuses the shared `_write_drained_results_row` IGNORING `count_inflight_verifications`,
  leaves abandoned pending runs `pending` (Open Q2); PATCH `/api/v3/tournaments/publish-results`
  (`tournaments:write`) → 409 on `NoAwaitingResultsEditionError`. New repo methods:
  `fetch_awaiting_results_editions`, `fetch_edition_child_cycles`,
  `mark_edition_start_announced`, `complete_edition`. `_EVENT_ROUTING`/`_build_event`
  dispatch `edition_results` → `api.tournament.results`; `_idempotency_key` derives the
  edition-scoped key per event type. TDD RED→GREEN per task (`f9496ed`/`1bfd53b` poller,
  `b471203`/`4a90a73` force-publish); `just lint-api` clean.

  - **Cleared the last 3 inherited failures.** Rewrote `test_edition_transitions.py`
    (`TestDrift`/`TestSingleEdition`/`TestHiatus`) to the poller-owns-results model
    (cron stops at `awaiting_results`/`finalizing`, writes no outbox row). TRUE full
    suite (`-n 4 --no-testmon`): **1831 passed / 2 skipped / 2 xfailed / 0 failures** —
    the prior `-n 4` flake also passed this run. Phase test debt fully retired.

  - **Deviations (both Rule 3 blocking):** (1) extended the `pending_transitions`
    event_type CHECK with `edition_results` in migration 0025 (the row write is core to
    this plan, was rejected by the 0024-era CHECK); (2) relocated the real-DB
    force-publish SERVICE tests from `tests/services/` to the integration suite
    (`services/conftest.py` makes `setup_test_db` a no-op, so `tournaments.*` only exists
    in the migrated integration DB).

- **12.1-03 complete (2026-06-01):** Repository + service verify/reject tri-state
  writes (D-08). `set_tournament_verified` now writes `SET status = $2`
  ('verified'/'rejected'; mapped from the kept bool signature) instead of the
  now-generated read-only `verified` column — preserving the `IS DISTINCT FROM`
  no-op idempotency guard (CR-01/WR-06), now keyed on `status`. Added
  `count_inflight_verifications(edition_id)` — `COUNT(*) ... JOIN cycles ON
  edition_id WHERE status='pending'` — the poller's drain signal (Plan 04).
  `fetch_tournament_completion` now returns `status`. Service `_set_verified`
  terminal guard (`status=='verified'` -> AlreadyVerifiedError, T-12.1-06) and
  no-op short-circuit (re-verify, T-12.1-07) rewritten to read `existing['status']`;
  the no-op verdict event derives `verified` from `status`. The atomic
  `_do(active_conn)` flip+participation-XP transaction wrapper is unchanged.
  TDD RED->GREEN per task (`e9a3622`/`30a8513` repo, `b272419`/`ec2018a` service);
  `just lint-api` clean.

  - **Cleared the 11 Wave-1-inherited failures.** Reject is now drain-detectable
    (writes `status='rejected'`, closing the D-08 indistinguishability bug). Fixed
    the shared `create_test_tournament_completion` fixture + two
    `test_tournaments_integration.py` seeds to write `status` (the `verified`
    column is generated). Full suite: **4 failed / 1814 passed** (down from the
    15-failure baseline) — the 4 remaining are the 3 Plan-04-owned
    `test_edition_transitions.py` (`awaiting_results` vs `completed`) + 1
    pre-existing `-n 4` flake. No new regressions.

- **12.1-02 complete (2026-06-01):** SDK wire contracts (D-09), interface-first.
  Added `TournamentEditionResultsEvent` (`edition_id`, `results:
  list[TournamentCycleCompletedEvent]`) on `api.tournament.results` (idempotency
  `tournament:results:{edition_id}`), exported in `__all__`. Added
  `results_pending: bool = False` as the LAST field on `TournamentRolloverEvent`
  — the default is a HARD backward-compat constraint (Pitfall 2): an OLD-shape
  `edition_rollover` outbox payload with no `results_pending` key still
  `msgspec.convert`s, so in-flight rows at deploy never get stuck unpublished.
  Extended `EditionStatus` Literal → `["active", "awaiting_results", "completed"]`.
  TDD RED (`ce2afc3`, ImportError confirmed) → GREEN (`bca32ed`); 6 SDK
  round-trip/compat tests pass; `just fix` reinstalled the editable workspace SDK;
  `just lint-sdk` clean. No deviations.

  - **Full-suite gate:** 15 failed / 1795 passed — identical to the 12.1-01
    baseline (11 owned by 12.1-03 `set_tournament_verified` generated-column write,
    3 owned by 12.1-04 timing-only-cron edition_transitions assertions, 1
    pre-existing `-n 4` flake). No new regressions from this SDK-only plan.

- **12.1-01 complete (2026-06-01):** Migration 0025 — verification-aware DB
  bedrock (D-06/D-08). Added tri-state `tournaments.completions.status`
  (`pending`/`verified`/`rejected`, CHECK-constrained) so "verification queue
  drained" is detectable (`COUNT(*) WHERE status='pending'`) and the illegal
  "verified AND rejected" state is unrepresentable. Re-added `verified` as a
  STORED generated column (`GENERATED ALWAYS AS (status = 'verified') STORED`)
  via the ordered swap (add status → backfill → drop ranking index → drop
  verified → re-add generated → recreate index, Pitfall 1) — every `verified DESC`
  ranking read + SDK `verified` field keeps working unchanged; only WRITES move
  to `status`. Extended the editions status CHECK with `awaiting_results` + added
  a `start_announced` marker. Rewrote `process_edition_transitions()` TIMING-ONLY:
  flips edition `active → awaiting_results`, child cycles → `finalizing`, creates
  N+1 grid-anchored, writes NO outbox row + NO snapshot (D-06). 7 Wave 0 schema
  tests authored RED then GREEN (22 passed in the file). `just lint-api` clean.

  - **Deviation (Rule 1, plan-owned):** fixed the pre-existing fresh-restart-wipe
    test seed to use `status='verified'` (the boolean is now generated).

  - **Carried-forward / deferred-by-design (see `deferred-items.md`):** the TRUE
    full suite (`-n 4 --no-testmon`) shows 15 failures — 11 owned by **12.1-03**
    (`set_tournament_verified` still does `SET verified = $2`, hits the generated
    column; verify/reject/leaderboard/cross-write), 3 owned by **12.1-04**
    (`test_edition_transitions.py` asserts the OLD cron-finalizes behavior; the
    timing-only cron correctly stops at `awaiting_results`), and 1 pre-existing
    `-n 4` flake (`test_filter_by_single_category`). None are 12.1-01 regressions;
    all resolved by downstream plans whose `files_modified` own the app code.

### Phase 12 Progress

- **12-05 complete (2026-06-01):** Bot combined-rollover consumer. Fused the
  `_on_cycle_started` + `_on_cycle_completed` pair into ONE `_on_edition_rollover`
  handler on `api.tournament.rollover` (`@queue_consumer(...,
  struct_type=TournamentRolloverEvent, idempotent=True)`, D-09), completing the DB →
  outbox → bot event path. Renders ONE CV2 LayoutView card with CONDITIONAL sections
  (D-10): a `## 🏅 Results` block iff `event.results`, a `## 🏁 New Cycle` block iff
  `event.started` — covering normal / into-hiatus / out-of-hiatus; a both-empty event
  posts nothing. Champion transfer iterates `event.results` FIRST (only when results
  present), reusing `_transfer_champion_role` verbatim (strip-all-then-grant, A6).
  Winners mentioned by numeric `<@id>` only, `AllowedMentions(users=allow-list,
  everyone=False, roles=False)`, ping inside a `ui.TextDisplay` (T-12-11); category/map
  fetched via the API on receipt (bot never reads Postgres, T-12-13). Dropped the
  deprecated `TournamentCyclesStarted/CompletedEvent` bot imports. Handler tests
  extended with the three conditional cases (`-k rollover` → 5 passed); full handler
  file 16 passed; `just lint-bot` clean. Wave-merge full suite: 7 failed (all
  deferred-by-design `test_cycle_transitions.py` 5 + `test_lifecycle_control.py` 2 —
  exactly as 12-04 predicted; no regressions) / 1801 passed.

- **12-04 complete (2026-06-01):** Routes + edition read. Moved pause/debug off
  per-category routes to config-level `PATCH /tournaments/pause` +
  `PATCH /tournaments/debug-cycle-length` (global, `tournaments:write`); cadence/anchor
  via `PATCH /tournaments/config`; bootstrap → `POST /tournaments/bootstrap`. Added
  `GET /tournaments/editions/active` (`tournaments:read`) surfacing the STORED
  `started_at`/`ends_at` (D-05/D-08, closes frontend-spec §8); 404 = `NoActiveEditionError`.
  `InvalidTimezoneError` → 422 on config PATCH (T-12-10); production debug guard → 403
  preserved (T-12-07). Per-cycle endpoints kept cycle-scoped (A5). NEW
  `tests/integration/test_config_tournament.py` (16 tests) proves scope guards
  (401/403 via a seeded non-superuser read-only token), the production debug-guard,
  and the stored-timing edition read.

  - **Deviation (plan-owned cleanup):** completed the `cycle_frequency` removal
    (cadence is global since 0024) the deferred-items doc assigned to 12-04 — dropped
    it from the category SDK structs + repo `create_category` + service create/update,
    resolving the 26-test `POST /categories` 500 cascade and un-xfailing repo
    `TestCreateCategory`. Fixed the downstream bot `/tournament info` to read the stored
    edition `ends_at` via a new `api.get_active_edition` (was deriving from cadence).
    Net full-suite: 35 → 7 failing (the 7 remaining = deferred-by-design
    `test_cycle_transitions.py` 5 + `test_lifecycle_control.py` 2; no regressions).
    `just lint-api`/`lint-sdk`/`lint-bot` all clean.

- **12-03 complete (2026-06-01):** Service + outbox edition re-wiring.
  `bootstrap_edition` grid-snaps the first edition via repo `next_grid_boundary()`
  (now() consulted only to pick the boundary, NEVER stored — D-08/D-13a), creating
  ONE edition + one child cycle per active category + ONE start-only
  `edition_rollover` outbox row (D-09). Global `set_transitions_paused` /
  `set_debug_cycle_length` config setters (pause = hiatus, D-12; production guard
  preserved, T-12-07). Added `fetch_active_edition` service wrapper for Plan 04's
  `GET /editions/active`. Outbox collapsed to ONE `TournamentRolloverEvent` per
  rollover keyed by `tournament:rollover:{edition_id}` (D-11); reward/streak
  side-effects iterate `event.results` once per child cycle keyed on `cycle_id`
  (D-10/Pattern 4); FOR UPDATE SKIP LOCKED publish-before-mark + deferred XP
  publish preserved. TDD RED→GREEN both tasks. Targeted suite 46 passed; reward
  integration 5 passed; `just lint-api` clean.

  - **Deviations:** added repo `next_grid_boundary`/`is_valid_timezone` helpers
    (three-layer) + `InvalidTimezoneError` (anchor_tz validation, T-12-04); thin
    route updates + deprecated `bootstrap_cycle` shim to keep lint clean until 12-04
    re-paths; adapted `test_tournament_rewards.py` to the `edition_rollover` seed
    (its outbox path was directly impacted).

  - **Carried-forward for 12-04:** the `create_category`/`cycle_frequency` cascade
    (27 `test_tournaments_integration.py` failures) + `test_cycle_transitions.py`
    (5) + `test_lifecycle_control.py` (2) remain deferred-by-design (see
    `deferred-items.md`); none are 12-03 regressions.

- **12-02 complete (2026-06-01):** SDK + repository edition contracts.
  `TournamentRolloverEvent` (edition_id/results/started — byte-identical to the
  0024 `edition_rollover` payload), `TournamentEditionResponse`, global
  cadence/anchor/pause/debug config structs; repo `create_edition` (param-bound
  grid timestamps, never `now()`), `create_cycle_for_edition`,
  `fetch_active_edition`, injection-safe global config setters, and
  `create_pending_transition` with nullable cycle_id + edition_id. Targeted repo
  suite 52 passed / 2 xfailed; lint-sdk + lint-api clean.

  - **Carried-forward for 12-03 (service wave):** `TournamentCategoryLifecycleResponse`
    kept as an importable alias to `TournamentLifecycleResponse`; per-category
    `set_category_paused`/`set_category_debug_cycle_seconds` kept as deprecated
    shims delegating to the global setters; `create_category` + its
    `TournamentCategoryCreateRequest` service call still bind dropped
    `cycle_frequency` (TestCreateCategory xfail-by-design). The old
    `test_cycle_transitions.py` / `test_lifecycle_control.py` failures remain
    deferred (outside this plan's files_modified).

- **12-01 complete (2026-06-01):** Migration 0024 edition overhaul. Adds
  `tournaments.editions` + child FK, global cadence/anchor/pause/debug config,
  `next_grid_boundary()` (DST-correct), `process_edition_transitions()`
  (status-only flip, `next.started_at = prev.ends_at`, never `now()` — the drift
  fix), one `edition_rollover` outbox row `{results, started, edition_id}`, and a
  PB-preserving fresh-restart wipe. Wave 0 scaffolds (grid/edition/schema) GREEN.

  - **Wipe bug caught & fixed:** `TRUNCATE ... CASCADE` would structurally truncate
    `core.completions` (FK into `tournaments.completions`), destroying PBs — replaced
    with ordered row-level DELETEs that honor `ON DELETE SET NULL` (D-15).

  - **Carried-forward for 12-02/12-03:** 11 pre-existing tournament tests
    (`test_cycle_transitions.py`, `test_lifecycle_control.py` pause/debug,
    `test_tournaments_repository.py::TestCreateCategory`) are stale-by-design
    against the dropped per-category columns / old function. See
    `deferred-items.md`; downstream plans rewrite the SDK/repo/service.

### Roadmap Evolution

- 2026-06-01: Reconstructed roadmap after v1.0 ship; added post-v1.0 quick-task track for cycle lifecycle control.
- Phase 12 added: Overhaul of tournaments
- Phase 12.1 inserted after Phase 12: Verification-aware tournament results: defer edition results until pending verifications drain (URGENT)
- Phase 14 added: Skill Score Dashboard — per-user skill-score snapshots, time-windowed line graph, summary stats, recent-changes feed with drill-down
- 2026-06-25: Phase 15 added: Dynamic Overwatch map management — drop the OverwatchMap Literal for runtime validation against maps.names (+ FK backstop), mixed-multipart upload endpoint (banner_url column), full-list /utilities/map-names endpoint + DB-fed moderator dropdown, idempotent regenerated seed for durability. Standalone post-v1.0 feature grounded in spikes 004–008.
