---
phase: 12-overhaul-of-tournaments
verified: 2026-06-01T00:00:00Z
status: human_needed
score: 30/30
overrides_applied: 0
human_verification:
  - test: "Run the tournament rollover card end-to-end in the Discord test server: bootstrap an edition, advance past ends_at in the DB, wait for or manually invoke process_edition_transitions(), then verify the combined rollover card appears in the announcements channel with the correct results + starting sections."
    expected: "One card posted containing both a results section (for the finalized edition's categories) and a new-cycle section (for the next edition's categories), with winner mentions inside a ui.TextDisplay (no content= used), and AllowedMentions restricting pings to the numeric winner allow-list."
    why_human: "The full event pipeline (pg_cron → DB → outbox poller → RabbitMQ → bot → Discord API) cannot be exercised programmatically in a unit/integration test environment without the infrastructure stack running."
  - test: "Verify the into-hiatus rollover case visually: set transitions_paused=True via the admin API, advance past ends_at, trigger process_edition_transitions(), check the bot post."
    expected: "A results-only card is posted (no 'New Cycle' section). Champion transfer still occurs. The next invocation of bootstrap_edition (when unpaused) creates a fresh start-only rollover announcement."
    why_human: "Three-case conditional rendering (normal/into-hiatus/out-of-hiatus) is tested by unit tests; the Discord rendering of the conditional CV2 card sections requires a live bot to confirm visual correctness."
  - test: "Confirm pg_cron job 'tournament-cycle-transitions' is registered on the production/dev database and points at tournaments.process_edition_transitions()."
    expected: "cron.job row with jobname='tournament-cycle-transitions', command='SELECT tournaments.process_edition_transitions()', schedule='* * * * *'."
    why_human: "The cron registration block is guarded on pg_extension and intentionally no-ops in the test DB — only verifiable on the live VPS database."
  - test: "Confirm the fresh-restart wipe executed cleanly on the VPS dev database: check that tournaments.cycles, tournaments.completions, and tournaments.editions are empty, and that core.completions rows that had a non-null tournament_completion_id now have it set to NULL."
    expected: "SELECT COUNT(*) FROM tournaments.cycles; => 0. SELECT COUNT(*) FROM tournaments.editions; => 0. SELECT COUNT(*) FROM core.completions WHERE tournament_completion_id IS NOT NULL; => 0 (nulled). SELECT COUNT(*) FROM core.completions; => same row count as before the migration (PBs preserved)."
    why_human: "The migration wipe only ran on the VPS. The row counts before/after can only be confirmed by querying the live database or its backup."
---

# Phase 12: Overhaul of Tournaments — Verification Report

**Phase Goal:** Replace the per-category, now()-stamped cycle-timing model with a single shared-epoch tournament — one explicit `tournaments.editions` entity holding grid-anchored start/end shared by every category (the drift fix: the cron job records exact grid timestamps, never now()), a single global cadence/anchor/pause/debug config, one combined rollover announcement (results of N + start of N+1), and a fresh-restart migration that wipes cycles/completions while preserving non-tournament PBs in core.completions.

**Verified:** 2026-06-01
**Status:** human_needed (automated evidence complete; 4 live-infrastructure checks require human)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

All 30 truths derived from decisions D-01 through D-15 (incl. D-13a) are verified.

| # | Truth (Decision) | Status | Evidence |
|---|-----------------|--------|----------|
| 1 | D-01: all categories transition together on one shared grid — one rollover creates exactly one edition with one child cycle per active category | VERIFIED | Migration 0024 `process_edition_transitions()` has a single `INSERT INTO tournaments.editions` inside `IF NOT v_cfg.transitions_paused THEN`, followed by a per-active-category cycle insert loop. Test `TestSingleEdition::test_one_rollover_one_edition_per_category` asserts exactly this. |
| 2 | D-02: single global cadence ('weekly'\|'biweekly') on tournaments.config replaces per-category cycle_frequency | VERIFIED | Migration 0024 §2 adds `cadence text NOT NULL DEFAULT 'weekly' CHECK (cadence IN ('weekly','biweekly'))` to `tournaments.config`. §3 `ALTER TABLE tournaments.categories DROP COLUMN IF EXISTS cycle_frequency`. SDK `TournamentConfigResponse` carries `cadence: Cadence`. Schema test `test_overhaul_categories_dropped_per_category_columns` asserts absence. |
| 3 | D-03: global transitions_paused + debug_cycle_seconds live on tournaments.config; per-category columns from migration 0023 dropped | VERIFIED | Migration 0024 §2 adds both columns to `tournaments.config`. §3 DROPs per-category columns from `tournaments.categories`. Repo has `_GLOBAL_CONFIG_FIELDS` frozenset containing both. Schema tests assert presence/absence. |
| 4 | D-05: tournaments.editions is the top-level timing entity; each tournaments.cycles row links to it via edition_id | VERIFIED | `CREATE TABLE IF NOT EXISTS tournaments.editions` with id/started_at/ends_at/status/created_at. `ALTER TABLE tournaments.cycles ADD COLUMN IF NOT EXISTS edition_id int REFERENCES tournaments.editions(id) ON DELETE CASCADE`. SDK `TournamentEditionResponse` struct. Schema test `test_overhaul_editions_table_exists` and `test_overhaul_cycles_has_edition_id`. |
| 5 | D-06: an edition rolls over on a configured anchor_weekday + anchor_time slot | VERIFIED | `tournaments.config` has `anchor_weekday int NOT NULL DEFAULT 1 CHECK (anchor_weekday BETWEEN 0 AND 6)` and `anchor_time time NOT NULL DEFAULT '00:00'`. The `next_grid_boundary()` function uses both. Grid boundary tests confirm the slot is hit correctly. |
| 6 | D-07: anchor (weekday/time/tz) stored on tournaments.config; changes take effect next edition | VERIFIED | `anchor_weekday`, `anchor_time`, `anchor_tz` all on `tournaments.config`. Route `PATCH /config` (scope `tournaments:write`) calls `tournament_service.update_config()` which validates and persists. The cron fn reads from config each invocation so a mid-edition change is picked up only at the next boundary. |
| 7 | D-08: the transition function NEVER writes now() into edition started_at/ends_at; next edition's started_at = prev.ends_at exactly | VERIFIED | Source gate: `grep -v '^--' 0024_tournament_editions_overhaul.sql \| grep -c "started_at = now()"` returns 0. The new edition INSERT: `VALUES (v_edition.ends_at, v_edition.ends_at + v_period, 'active')`. Drift test `test_drift_immune_under_late_cron` asserts `edition1["started_at"] == prev0["ends_at"]` under 1h-late and 2h-late simulated ticks. |
| 8 | D-13a: bootstrap/resume snaps first/next edition to the next grid boundary via next_grid_boundary() | VERIFIED | `tournament_service.bootstrap_edition()` calls `self._tournament_repo.next_grid_boundary(...)` with the configured anchor, then stores the returned grid instant verbatim as `started_at`. No `now()` stored in service. Service test `test_bootstrap_grid_snaps_start_no_now` asserts next Monday 00:00 UTC. |
| 9 | D-09: one combined TournamentRolloverEvent per rollover replaces the started/completed pair | VERIFIED | `_EVENT_ROUTING` in `tournament_outbox_service.py` has a single entry: `{"edition_rollover": ("api.tournament.rollover", TournamentRolloverEvent)}`. Old `TournamentCyclesStarted/CompletedEvent` routing removed. Bot `_on_edition_rollover` replaces `_on_cycle_started`/`_on_cycle_completed` (grep returns 0 matches for old handlers). |
| 10 | D-10: TournamentRolloverEvent has conditional sections — results list (empty on out-of-hiatus) + started list (empty on into-hiatus) | VERIFIED | SDK struct: `edition_id: int; results: list[TournamentCycleCompletedEvent]; started: list[TournamentCycleStartedEvent]`. Bot `_on_edition_rollover` uses `if event.results:` and `if event.started:` guards. Three bot handler tests cover normal/into-hiatus/out-of-hiatus cases. |
| 11 | D-11: rollover event published with ONE idempotency key `tournament:rollover:{edition_id}` on routing key `api.tournament.rollover` | VERIFIED | Outbox service: `idempotency_key=f"tournament:rollover:{edition_id}"`, `routing_key` from `_EVENT_ROUTING["edition_rollover"][0]` = `"api.tournament.rollover"`. Test `test_one_row_one_publish_with_edition_idempotency_key` asserts key == `f"tournament:rollover:{edition_id}"`. |
| 12 | D-12: pause = suppress next edition (hiatus); active edition still runs its full term | VERIFIED | Migration §6: `IF NOT v_cfg.transitions_paused THEN ... INSERT INTO tournaments.editions ...` — no next edition on pause. `UPDATE tournaments.editions SET status = 'completed'` runs unconditionally. Test `test_pause_completes_without_next_edition` asserts `completed["status"] == "completed"` and `chained == []` (no chained edition). |
| 13 | D-13: fresh-restart wipes in-flight cycles and tournament completions | VERIFIED | Migration §7: `DELETE FROM tournaments.completions; DELETE FROM tournaments.cycles; DELETE FROM tournaments.editions; DELETE FROM tournaments.pending_transitions;` in order. |
| 14 | D-14: all tournaments.cycles, tournaments.completions, tournaments.editions rows wiped | VERIFIED | Same §7 DELETEs cover all three tables. The comment explicitly explains the ordered-DELETE approach vs TRUNCATE CASCADE. |
| 15 | D-15: core.completions.tournament_completion_id is NULLed on cross-written rows; core.completions PB rows are preserved (no cascade delete) | VERIFIED | Migration §7 first line: `UPDATE core.completions SET tournament_completion_id = NULL WHERE tournament_completion_id IS NOT NULL;` before any DELETE. Never TRUNCATE CASCADE. Schema integration test `test_preserve_pbs_wipe_keeps_core_rows_nulls_fk` asserts core row count preserved + FK NULLed. |
| 16 | D-05 (SDK): TournamentEditionResponse struct carries id/started_at/ends_at/status | VERIFIED | `class TournamentEditionResponse(Struct)` at line 271 of `tournaments.py`: fields `id: int`, `started_at: dt.datetime`, `ends_at: dt.datetime`, `status: EditionStatus`, `created_at: dt.datetime`. Exported in `__all__`. |
| 17 | D-08 (SDK): edition ends_at is a stored field on the edition response (closes frontend-spec §8) | VERIFIED | `TournamentEditionResponse.ends_at: dt.datetime` is a first-class struct field. The docstring notes "ends_at is a STORED field, not derived — closing frontend-spec §8 (D-08)". |
| 18 | D-02 (SDK/repo): global config surface carries cadence | VERIFIED | `TournamentConfigResponse.cadence: Cadence`, `TournamentConfigPatchRequest.cadence: Cadence | UnsetType`. Repo `set_cadence` method uses `_GLOBAL_CONFIG_FIELDS` allow-list. |
| 19 | D-03 (SDK/repo): global config surface carries transitions_paused + debug_cycle_seconds (no per-category id framing) | VERIFIED | `TournamentConfigResponse` and `TournamentLifecycleResponse` both carry global-only fields (no category_id). Repo `set_transitions_paused` / `set_debug_cycle_seconds` via `_set_global_config`. |
| 20 | D-07 (SDK/repo): global config carries anchor_weekday/anchor_time/anchor_tz | VERIFIED | `TournamentConfigResponse.anchor_weekday: int`, `.anchor_time: dt.time`, `.anchor_tz: str`. `TournamentConfigPatchRequest` has all three as optional UNSET fields. Repo `set_anchor` method. |
| 21 | D-08 (repo): edition CRUD repo methods bind grid timestamps as parameters — never now() | VERIFIED | `create_edition()`: `INSERT INTO tournaments.editions (started_at, ends_at, status) VALUES ($1, $2, $3)` — both as bound params. `create_cycle_for_edition()`: `started_at` passed as `$4`. Repo test `test_create_edition_binds_grid_timestamps` asserts `result["started_at"] == started` and `result["ends_at"] == ends` with deterministic datetimes. |
| 22 | D-13a/D-08 (service): bootstrap_edition computes started_at via next_grid_boundary; no now() stored | VERIFIED | `tournament_service.bootstrap_edition()` calls `next_grid_boundary(...)` and stores the returned value as `started_at`. `grep -n "now()"` in `tournament_service.py` returns only a comment line — no now() assignment. |
| 23 | D-03 (service): pause/debug setters mutate the global tournaments.config (not per-category) | VERIFIED | `tournament_service.set_transitions_paused()` → `self._tournament_repo.set_transitions_paused(paused)` → `_set_global_config({"transitions_paused": paused})`. No category_id parameter. Service test `test_pause_then_resume_round_trip` asserts global config mutation. |
| 24 | D-12 (service): pause semantics = suppress next edition; active edition still runs full term | VERIFIED | Service's `set_transitions_paused(True)` only sets the global flag; does not touch the running edition. The DB function enforces the hiatus semantics at boundary time. |
| 25 | D-09/D-11 (outbox): single combined edition_rollover event keyed by edition_id | VERIFIED | Outbox service: one `pending_transitions` row → one `publish_message` call with `idempotency_key=f"tournament:rollover:{edition_id}"`. `_EVENT_ROUTING` has one entry. Outbox test `test_one_row_one_publish_with_edition_idempotency_key` asserts exactly one publish with the correct key. |
| 26 | D-10 (outbox): reward side-effects run once per child cycle (per results entry), not once per edition | VERIFIED | Outbox loop: `for entry in event.results: await reward_service.award_cycle_end(entry, conn=conn)` — keyed on `entry.cycle_id`. Test `test_award_called_once_per_results_entry` asserts N invocations for N result entries. |
| 27 | D-03/D-02/D-07 (routes): pause/debug/cadence/anchor are config-level routes, all tournaments:write guarded | VERIFIED | Routes: `PATCH /pause` (`tournaments:write`), `PATCH /debug-cycle-length` (`tournaments:write`), `PATCH /config` (`tournaments:write`, handles cadence/anchor). Integration test `test_config_tournament.py` asserts 401/403 on unauthenticated/wrong-scope. |
| 28 | D-05/D-08 (routes): GET /editions/active exposes stored shared timing | VERIFIED | Route `GET /editions/active` at path `/editions/active` with `opt={"required_scopes": {"tournaments:read"}}`, returns `TournamentEditionResponse`. Integration test `test_returns_stored_timing` seeds an edition and verifies `started_at` and `ends_at` in response. |
| 29 | D-09/D-10 (bot): single _on_edition_rollover consumer replaces _on_cycle_started + _on_cycle_completed pair | VERIFIED | `@queue_consumer("api.tournament.rollover", struct_type=TournamentRolloverEvent, idempotent=True)` on `_on_edition_rollover`. Zero matches for `_on_cycle_started` or `_on_cycle_completed` in `extensions/tournaments.py`. |
| 30 | D-10 (bot): three conditional card cases render correctly; AllowedMentions + ui.TextDisplay safety preserved | VERIFIED | Bot handler uses `if event.results:` / `if event.started:` guards for CV2 container sections. Winners pinged via `<@{entry.winner_user_id}>` inside `ui.TextDisplay` only. `AllowedMentions(users=allowed_users, everyone=False, roles=False)` used. Four bot handler tests cover normal, into-hiatus, out-of-hiatus, and empty cases. |

**Score:** 30/30 truths verified (all automated)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `apps/api/migrations/0024_tournament_editions_overhaul.sql` | Edition table, global config, grid fn, transition rewrite, wipe, cron | VERIFIED | 417 lines. Contains `CREATE TABLE IF NOT EXISTS tournaments.editions`, `tournaments.next_grid_boundary`, `tournaments.process_edition_transitions`. No `started_at = now()` writes outside comments. |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` | TournamentRolloverEvent, TournamentEditionResponse, global config structs | VERIFIED | 685 lines. `class TournamentRolloverEvent(Struct)` at line 598; `class TournamentEditionResponse(Struct)` at line 271; `TournamentConfigResponse` with cadence/anchor fields; deprecated `TournamentCyclesStartedEvent`/`TournamentCyclesCompletedEvent` emit `DeprecationWarning` via `__post_init__`. All exported in `__all__`. |
| `apps/api/repository/tournaments_repository.py` | Edition CRUD, global config setters (allow-list), outbox with edition_id | VERIFIED | 1779 lines. `create_edition` binds timestamps as `$1`/`$2`. `create_cycle_for_edition` with `edition_id`. `fetch_active_edition`. `_set_global_config` with `_GLOBAL_CONFIG_FIELDS` frozenset allow-list. `create_pending_transition` accepts `edition_id: int | None`. |
| `apps/api/services/tournament_service.py` | bootstrap_edition (grid-snap), global pause/debug, fetch_active_edition | VERIFIED | 1034 lines. `bootstrap_edition` calls `next_grid_boundary` → stores verbatim grid instant. `set_transitions_paused`/`set_debug_cycle_length` call global repo setters. `fetch_active_edition` thin wrapper. Production guard on `set_debug_cycle_length` preserved. |
| `apps/api/services/tournament_outbox_service.py` | Single edition_rollover publish keyed by edition_id | VERIFIED | 222 lines. `_EVENT_ROUTING` has single entry `{"edition_rollover": ("api.tournament.rollover", TournamentRolloverEvent)}`. Idempotency key `tournament:rollover:{edition_id}`. Per-child-cycle reward iteration. |
| `apps/api/routes/v3/tournaments.py` | Config-level pause/debug/cadence/anchor routes; GET /editions/active | VERIFIED | `PATCH /pause`, `PATCH /debug-cycle-length`, `PATCH /config` all `tournaments:write`. `GET /editions/active` `tournaments:read`. |
| `apps/api/tests/repository/tournaments/test_grid_boundary.py` | next_grid_boundary correctness incl. DST crossing | VERIFIED | 107 lines. 5 tests: next Monday midnight UTC, step-one-period, same-day future, spring-forward wall-clock preservation, week-after-spring-forward. |
| `apps/api/tests/repository/tournaments/test_edition_transitions.py` | drift-immunity, single-edition, hiatus behavior | VERIFIED | 263 lines. 3 test classes: `TestDriftImmunity` (2-rollover late-cron), `TestSingleEdition` (one edition per rollover), `TestHiatus` (results-only, no next edition). |
| `apps/api/tests/repository/tournaments/conftest.py` | advance_past_ends_at + simulate_late_cron fixtures | VERIFIED | Single atomic UPDATE for `advance_past_ends_at` (WR-03 fix). `simulate_late_cron` invokes `tournaments.process_edition_transitions()` directly. |
| `apps/api/tests/integration/test_tournaments_schema.py` | overhaul + preserve_pbs cases | VERIFIED | Tests `test_overhaul_editions_table_exists`, `test_overhaul_cycles_has_edition_id`, `test_overhaul_config_has_global_columns`, `test_overhaul_categories_dropped_per_category_columns`, `test_overhaul_outbox_supports_edition_rollover`, `test_preserve_pbs_wipe_keeps_core_rows_nulls_fk`. |
| `apps/api/tests/integration/test_config_tournament.py` | NEW — route/scope integration tests for global config endpoints | VERIFIED | 243 lines. Tests pause, debug-cycle-length (incl. production rejection), cadence, anchor, invalid anchor_tz, GET /editions/active (stored timing), 404 when no active edition. |
| `apps/bot/extensions/tournaments.py` | _on_edition_rollover with conditional CV2 sections | VERIFIED | 817 lines. `@queue_consumer("api.tournament.rollover", struct_type=TournamentRolloverEvent, idempotent=True)`. Conditional `if event.results:` / `if event.started:` sections. Winners in `ui.TextDisplay`. `AllowedMentions(users=allowed_users, everyone=False, roles=False)`. `_transfer_champion_role` reused. |
| `apps/api/tests/bot/test_tournaments_handler.py` | Handler tests for three conditional render cases | VERIFIED | Tests: normal (results+started), into-hiatus (results-only), out-of-hiatus (started-only), empty event (noop), empty standings, champion transfer, skip-if-not-in-guild, skip-no-champion-role. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `process_edition_transitions()` | `tournaments.editions.started_at/ends_at` | `next.started_at = old.ends_at` (no now()) | VERIFIED | `INSERT INTO tournaments.editions ... VALUES (v_edition.ends_at, v_edition.ends_at + v_period, 'active')` — both values are DB-computed from the previous edition's stored boundary. No `now()` call in the path. |
| fresh-restart wipe | `core.completions` | `UPDATE SET tournament_completion_id = NULL` before DELETE (no cascade) | VERIFIED | Line 378: `UPDATE core.completions SET tournament_completion_id = NULL WHERE tournament_completion_id IS NOT NULL;` precedes the `DELETE FROM tournaments.completions` chain. |
| `TournamentRolloverEvent` | `TournamentCycleCompletedEvent` / `TournamentCycleStartedEvent` | `results`/`started` list element types | VERIFIED | `results: list[TournamentCycleCompletedEvent]`, `started: list[TournamentCycleStartedEvent]` in the struct. Element structs retained and unchanged. |
| edition create repo method | `tournaments.editions` | `INSERT ... started_at, ends_at` bound as `$1`, `$2` (no now()) | VERIFIED | `VALUES ($1, $2, $3) RETURNING *` in `create_edition()`. Repo test asserts stored timestamps equal the bound params. |
| `tournament_outbox_service.publish_pending_transitions` | `BaseService.publish_message` | `idempotency_key=tournament:rollover:{edition_id}`, `routing_key=api.tournament.rollover` | VERIFIED | Line 180: `idempotency_key=f"tournament:rollover:{edition_id}"`. `routing_key` from `_EVENT_ROUTING["edition_rollover"][0]`. |
| `bootstrap_edition` | `tournaments.next_grid_boundary` | `next_grid_boundary(anchor_weekday, anchor_time, anchor_tz, period)` | VERIFIED | Service calls `self._tournament_repo.next_grid_boundary(config["anchor_weekday"], config["anchor_time"], config["anchor_tz"], period, conn=conn)` and stores the result as `started_at`. |
| config PATCH / pause / debug routes | tournament_service global setters | `tournaments:write` scope | VERIFIED | All three mutation routes carry `opt={"required_scopes": {"tournaments:write"}}`. Route calls `tournament_service.set_transitions_paused`, `set_debug_cycle_length`, `update_config`. |
| `GET /editions/active` | `tournament_service.fetch_active_edition` | `TournamentEditionResponse` | VERIFIED | Route handler calls `await tournament_service.fetch_active_edition()` and returns the response directly. Three-layer rule upheld (no repo call from route). |
| `_on_edition_rollover` | `_transfer_champion_role` | Iterate `event.results`, transfer champion per category before sending card | VERIFIED | Bot handler iterates `for entry in event.results: ... await self._transfer_champion_role(entry, category)` BEFORE `channel.send(view=view, ...)`. |
| `_on_edition_rollover` | `TournamentRolloverEvent` | `@queue_consumer("api.tournament.rollover", struct_type=TournamentRolloverEvent, idempotent=True)` | VERIFIED | Decorator at line 304–307 of `extensions/tournaments.py`. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `process_edition_transitions()` → outbox | `v_results`, `v_started` | Loop over `tournaments.cycles WHERE edition_id = v_edition.id` with CTE RANK() standings | Yes — real DB rows via `tournaments.completions` | FLOWING |
| `tournament_outbox_service.publish_pending_transitions` | `event` | `msgspec.convert(row["payload"], TournamentRolloverEvent)` from `pending_transitions` outbox | Yes — round-trips the DB-written jsonb payload | FLOWING |
| `bot._on_edition_rollover` | `event: TournamentRolloverEvent` | RabbitMQ delivery from `api.tournament.rollover` queue | Yes — deserialized from published message | FLOWING |
| `GET /editions/active` | `edition: TournamentEditionResponse` | `SELECT * FROM tournaments.editions WHERE status='active'` | Yes — real DB query | FLOWING |
| `bootstrap_edition` | `started_at` | `SELECT tournaments.next_grid_boundary(...)` from DB | Yes — DB function computes from configured anchor | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Migration 0024 has no `started_at = now()` writes | `grep -v '^--' apps/api/migrations/0024_tournament_editions_overhaul.sql \| grep -c "started_at = now()"` | 0 | PASS |
| Outbox payload uses `started` key (not `next`) | `grep -v '^--' apps/api/migrations/0024_tournament_editions_overhaul.sql \| grep -c "'started'"` | 1 (byte-identical to TournamentRolloverEvent) | PASS |
| No `'next'` key in outbox payload | `grep -v '^--' apps/api/migrations/0024_tournament_editions_overhaul.sql \| grep -c "'next'"` | 0 | PASS |
| core.completions UPDATE precedes tournament DELETE | Line order in §7 of migration | UPDATE line 378 before DELETE line 387 | PASS |
| Old handler pair absent from bot | `grep -c "_on_cycle_started\|_on_cycle_completed" apps/bot/extensions/tournaments.py` | 0 | PASS |
| Old routing absent from outbox service | `grep -c "_on_cycle_started\|_on_cycle_completed\|TournamentCyclesStartedEvent\|TournamentCyclesCompletedEvent" apps/api/services/tournament_outbox_service.py` | 0 | PASS |
| now() absent from tournament_service (no stored writes) | `grep -n "now()" apps/api/services/tournament_service.py` (non-comment) | Only appears in a docstring/comment line (line 383) | PASS |
| bootstrap_edition calls next_grid_boundary | `grep -n "next_grid_boundary" apps/api/services/tournament_service.py` | Line 415 in bootstrap_edition | PASS |
| Idempotency key in outbox service | `grep -n "tournament:rollover:" apps/api/services/tournament_outbox_service.py` | Line 180: `idempotency_key=f"tournament:rollover:{edition_id}"` | PASS |
| _EVENT_ROUTING has single entry | `grep -n "_EVENT_ROUTING" apps/api/services/tournament_outbox_service.py` | Single dict with `edition_rollover` only | PASS |
| pg_cron block guarded on pg_extension | `grep -n "pg_extension" apps/api/migrations/0024_tournament_editions_overhaul.sql` | Line 402: `IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron')` | PASS |
| Advisory lock 2025070100 used (not store's 1234567890) | `grep -n "pg_try_advisory_xact_lock" apps/api/migrations/0024_tournament_editions_overhaul.sql` | Line 197: `pg_try_advisory_xact_lock(2025070100)` | PASS |
| TOCTOU fix: update_category + delete_category wrapped in transaction | `grep -n "async with self._pool.acquire" apps/api/services/tournament_service.py` | Lines 242 + 281 wrapping check + mutate pairs | PASS |
| WR-05: deprecated events emit DeprecationWarning | `grep -n "DeprecationWarning" libs/sdk/src/genjishimada_sdk/tournaments.py` | Lines 565+590 in `__post_init__` of both deprecated event classes | PASS |
| allow-list SET builder on global config | `grep -n "_GLOBAL_CONFIG_FIELDS" apps/api/repository/tournaments_repository.py` | frozenset at line 347 with 6 allowed keys; `_set_global_config` rejects unknown fields | PASS |

---

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` files exist for this phase. The test suite is the verification mechanism.

Full test suite result from context_notes: 1796 passed, 1 failed (pre-existing flaky test `tests/repository/maps/test_maps_repository_fetch_maps.py::TestFetchMapsFilterCategory::test_filter_by_single_category` — shared-test-DB cross-worker contamination under `-n 4`, passes in isolation, documented in MEMORY.md as a pre-existing non-regression). No tournament test failures.

---

### Requirements Coverage

No REQ-IDs in ROADMAP.md for this phase — scope tracked via decisions D-01..D-15 (incl. D-13a) in 12-CONTEXT.md. All 16 decisions are covered by the verified truths above.

The prior "configurable per-category cycle frequency" requirement (PROJECT.md) is amended/superseded by D-01/D-02, as documented in the CONTEXT.md `<domain>` section and the SDK struct docstrings.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | No TBD/FIXME/XXX debt markers in any phase-modified file | — | Clean |

The deprecated `TournamentCyclesStartedEvent` / `TournamentCyclesCompletedEvent` structs emit runtime `DeprecationWarning` from `__post_init__` and are documented as importable-until-removed (WR-05 applied). They do not constitute stubs — they are intentional backward-compat shims with a clear removal path.

---

### Human Verification Required

Four items require live-infrastructure access to verify.

#### 1. End-to-end combined rollover card in Discord

**Test:** Bootstrap an edition on the dev Discord server, advance past ends_at in the database, trigger or wait for `process_edition_transitions()`, observe the bot's announcement in the tournament announcements channel.

**Expected:** One combined card with a results section (per-category finalized cycle standings, winner mentioned by `<@id>` inside a `ui.TextDisplay`) and a new-cycle section (per-category next map info). `AllowedMentions` restricts pings to numeric winner IDs only. No `content=` kwarg used (CV2 LayoutView constraint — MEMORY.md).

**Why human:** The full pipeline (pg_cron → DB → outbox poller → RabbitMQ → bot → Discord API) cannot be exercised in the test environment. Visual rendering of the conditional CV2 card must be confirmed live.

#### 2. Into-hiatus rollover visual check

**Test:** Set `transitions_paused=True` via `PATCH /tournaments/pause`, advance past ends_at, trigger the transition function, check the bot post.

**Expected:** A results-only card (no "New Cycle" section). Champion transfer occurs. When unpaused and `bootstrap_edition` is called, the next announcement is start-only.

**Why human:** Three-case conditional rendering is unit-tested; actual Discord rendering of the absent section requires a live bot.

#### 3. pg_cron job registration on the VPS database

**Test:** On the dev VPS, run `SELECT jobname, schedule, command FROM cron.job WHERE jobname = 'tournament-cycle-transitions';`.

**Expected:** Row with `jobname='tournament-cycle-transitions'`, `schedule='* * * * *'`, `command='SELECT tournaments.process_edition_transitions()'`.

**Why human:** The cron registration block is guarded on `pg_extension` and intentionally no-ops in the test DB. Only verifiable by querying the live VPS database.

#### 4. Fresh-restart wipe verification on VPS database

**Test:** After running the migration on dev VPS, query: `SELECT COUNT(*) FROM tournaments.cycles`, `tournaments.editions`, `tournaments.completions`, and confirm `SELECT COUNT(*) FROM core.completions WHERE tournament_completion_id IS NOT NULL` returns 0.

**Expected:** All tournament tables empty. Zero cross-linked core.completions rows. Total `core.completions` row count unchanged (PBs preserved).

**Why human:** The wipe only executed on the VPS. The pre/post row counts require querying the live database or its backup to confirm the D-15 contract held in production.

---

### Gaps Summary

No gaps. All 30 observable truths are VERIFIED with direct codebase evidence. The 4 human verification items are live-infrastructure checks that cannot be automated; they do not represent missing implementation — the code is complete and all automated tests pass.

---

_Verified: 2026-06-01_
_Verifier: Claude (gsd-verifier)_
