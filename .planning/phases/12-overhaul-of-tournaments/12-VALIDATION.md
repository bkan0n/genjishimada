---
phase: 12
slug: overhaul-of-tournaments
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-01
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (pytest-asyncio auto, pytest-databases[postgres]) |
| **Config file** | apps/api/pyproject.toml |
| **Quick run command** | `uv run --directory apps/api pytest tests/<targeted> -p no:xdist` |
| **Full suite command** | `uv run --directory apps/api pytest -n 4 --no-testmon` |
| **Estimated runtime** | ~120 seconds (full), ~10s (targeted) |

---

## Sampling Rate

- **After every task commit:** Run targeted quick command for affected test file
- **After every plan wave:** Run full suite command (`-n 4 --no-testmon` — true full run; testmon caching can hide failures)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Task 0 | 12-01 | 1 | D-06/D-07/D-08 (Wave 0 scaffolds) | T-12-03 | RED scaffolds fail loudly until grid fn + edition schema exist (no silent skips) | integration (DB fn) | `uv run --directory apps/api pytest tests/repository/tournaments/test_grid_boundary.py tests/repository/tournaments/test_edition_transitions.py --no-testmon -p no:xdist` | ❌ NEW (Wave 0 — this task creates them) | ⬜ pending |
| Task 1 | 12-01 | 1 | D-01/D-02/D-03/D-05/D-06/D-07/D-08/D-12/D-13/D-14/D-15 | T-12-01/T-12-02/T-12-03 | No `now()` into edition timestamps; advisory lock 2025070100; payload keys `results`/`started`/`edition_id`; wipe NULLs FK before TRUNCATE (no cascade) | integration (migration + DB fn) | `uv run --directory apps/api pytest tests/repository/tournaments/test_grid_boundary.py tests/repository/tournaments/test_edition_transitions.py tests/integration/test_tournaments_schema.py -k "drift or single_edition or hiatus or overhaul or preserve_pbs or grid" --no-testmon -p no:xdist` | ✅ test_tournaments_schema.py exists; ❌ grid/edition files created in Task 0 (Wave 0 dep) | ⬜ pending |
| Task 2 | 12-01 | 1 | D-13/D-14/D-15 (FK-safe wipe) | T-12-01 | core.completions PB rows preserved; tournament_completion_id NULLed; per-category columns dropped | integration (migration) | `uv run --directory apps/api pytest tests/integration/test_tournaments_schema.py -k "overhaul or preserve_pbs" --no-testmon -p no:xdist` | ✅ exists (extend in place) | ⬜ pending |
| Task 1 | 12-02 | 2 | D-05/D-09/D-10/D-11 (SDK structs) | T-12-06 | Struct field names (`results`/`started`/`edition_id`) byte-identical to migration payload; msgspec.convert round-trip proves it (fail-closed on drift) | unit (msgspec round-trip) | `just fix && uv run --directory apps/api python -c "from genjishimada_sdk.tournaments import TournamentRolloverEvent, TournamentEditionResponse; import msgspec; print(msgspec.convert({'edition_id':1,'results':[],'started':[]}, TournamentRolloverEvent))"` | ✅ tournaments.py exists (extend) | ⬜ pending |
| Task 2 | 12-02 | 2 | D-05/D-09 (repo edition CRUD + outbox edition_id) | T-12-03/T-12-05 | Edition-create methods bind started_at/ends_at as `$1`/`$2` (no `now()`); config SET builder uses allow-listed field names + positional params | integration (repo) | `uv run --directory apps/api pytest tests/repository/tournaments/test_tournaments_repository.py --no-testmon -p no:xdist` | ✅ test_tournaments_repository.py exists (extend) | ⬜ pending |
| Task 1 | 12-03 | 3 | D-03/D-08/D-12/D-13a (service bootstrap + global setters) | T-12-04/T-12-07/T-12-03 | bootstrap_edition uses next_grid_boundary (no stored `now()`); debug setter keeps `APP_ENVIRONMENT=='production'` reject; anchor_tz validated against pg_timezone_names | service (TDD: RED→GREEN) | `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/services/test_tournament_lifecycle.py --no-testmon -p no:xdist` | ✅ both exist (extend per TDD ordering note) | ⬜ pending |
| Task 2 | 12-03 | 3 | D-09/D-10/D-11 (one combined event) | T-12-08 | Single idempotency key `tournament:rollover:{edition_id}`; publish-before-mark at-least-once loop preserved; reward grants once per child cycle (xp_grants ledger guards double-grant) | service (TDD: RED→GREEN) | `uv run --directory apps/api pytest tests/repository/tournaments/test_outbox_poller.py -k "rollover or idempoten" --no-testmon -p no:xdist` | ✅ exists (extend per TDD ordering note) | ⬜ pending |
| Task 1 | 12-04 | 4 | D-02/D-03/D-05/D-07/D-08 (config-level routes + edition read) | T-12-09/T-12-07/T-12-10 | Every config mutation route declares `required_scopes: tournaments:write`; edition read `tournaments:read`; unauthenticated/wrong-scope → 401/403; production debug-guard | integration (route/scope) | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py tests/integration/test_config_tournament.py --no-testmon -p no:xdist` | ✅ test_tournaments_integration.py exists; ❌ test_config_tournament.py NEW (created in this task) | ⬜ pending |
| Task 1 | 12-05 | 4 | D-09/D-10/D-11 (bot rollover handler) | T-12-11/T-12-12/T-12-13 | Single `_on_edition_rollover` (idempotent consumer); winners mentioned by numeric `<@id>` only with AllowedMentions allow-list; bot never writes Postgres | bot (event payload) | `uv run --directory apps/api pytest tests/bot/test_tournaments_handler.py -k "rollover" --no-testmon -p no:xdist` | ✅ test_tournaments_handler.py exists (extend) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> Nyquist note: every code-producing task above has an `<automated>` verify. Tasks whose test files are marked ❌ NEW are either the Wave 0 scaffold task itself (12-01 Task 0) or a task that creates the file as part of its own deliverable (12-04 Task 1 creates `test_config_tournament.py`); no code task is left without an automated verify or a satisfied Wave 0 dependency.

---

## Wave 0 Requirements

- [ ] Migration applies cleanly against the pytest-databases test database (grid-anchored transition fn, edition table, fresh-restart wipe) — 12-01 Task 1
- [ ] Fixtures: clock/grid-boundary control so late-cron drift-immunity can be asserted deterministically (`advance_past_ends_at`, `simulate_late_cron` in conftest) — 12-01 Task 0
- [ ] New scaffolds `test_grid_boundary.py` + `test_edition_transitions.py` fail RED for the right reason (missing schema, not import errors) — 12-01 Task 0
- [ ] Existing tournament test infrastructure covers cycle/outbox/leaderboard/schema/handler seams — extend, do not replace (12-02 repo, 12-03 service+outbox, 12-04 integration, 12-05 bot)

---

## Manual-Only Verifications

*If none: "All phase behaviors have automated verification."*

All phase behaviors have automated verification. The bot rollover card's conditional sections (D-10 normal / into-hiatus / out-of-hiatus) are asserted against the event payload and handler logic in `tests/bot/test_tournaments_handler.py -k rollover`; final Discord visual rendering is incidental, not a gate.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (grid/edition scaffolds + conftest fixtures in 12-01 Task 0; NEW test_config_tournament.py created in 12-04 Task 1)
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
