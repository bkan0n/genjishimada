---
phase: 10
slug: bot-slash-commands
status: final
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-30
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (API side) — `pytest-asyncio` (auto mode), `pytest-databases[postgres]`, `pytest-xdist` |
| **Config file** | `apps/api/pyproject.toml` (`[tool.pytest.ini_options]`, `addopts = "--testmon"`) |
| **Quick run command** | `uv run --directory apps/api pytest tests/<target> -v -p no:xdist` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~60–120 seconds (full); seconds (targeted) |

> Note: API-side behavior (the new streak endpoint + service) is automatable with pytest.
> Bot-side slash-command behavior (Discord interactions, embeds, autocomplete, role gate,
> paginator) is exercised by bot-side unit tests under `apps/api/tests/bot/` using the path-load
> + stubbed-bot pattern (`test_tournaments_handler.py:44-73`) — no live Discord. Behaviors that
> genuinely require a Discord gateway / visual rendering are listed under Manual-Only.
> MEMORY note: multi-file pytest runs need `--no-testmon` (testmon deselects when multiple files
> are passed); single-file runs are fine.

---

## Sampling Rate

- **After every task commit:** Run the targeted quick command for the touched module (the `-k` selector for that task in the map below)
- **After every plan wave:** Run the per-wave merge command (`--no-testmon`)
- **Before `/gsd:verify-work`:** Full API suite (`just test-api`) must be green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01 Task 1 | 10-01 | 1 | ADM-03 | T-10-02 | Scope `tournaments:read` enforced (401/403 without scope) — RED Wave-0 test | unit + integration (RED) | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -k GetStreak -v -p no:xdist` | `apps/api/tests/services/test_tournament_service.py`, `apps/api/tests/integration/test_tournaments_integration.py` | ⬜ pending |
| 10-01 Task 2 | 10-01 | 1 | ADM-03 / D-01 | T-10-01, T-10-02, T-10-03 | get_streak raises StreakNotFoundError → route 404 (no fabricated zero); scope guard on route | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -k GetStreak -v -p no:xdist && uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py -k GetStreak -v -p no:xdist` | `apps/api/services/exceptions/tournaments.py`, `apps/api/services/tournament_service.py`, `apps/api/routes/v3/tournaments.py` | ⬜ pending |
| 10-02 Task 1 | 10-02 | 1 | ADM-03 | T-10-06 | Six typed wrappers; correct verbs (POST reroll / PATCH next-cycle) | static (lint + type-check) | `uv run --directory apps/bot ruff check extensions/api_service.py && uv run --directory apps/bot basedpyright extensions/api_service.py` | `apps/bot/extensions/api_service.py` | ⬜ pending |
| 10-02 Task 2 | 10-02 | 1 | ADM-03 / D-09 | T-10-04 | CategoryTransformer validates free-text against live list; unknown name → UserFacingError; ≤25 choices | static (lint + type-check) + Manual-Only autocomplete | `uv run --directory apps/bot ruff check utilities/transformers.py && uv run --directory apps/bot basedpyright utilities/transformers.py` | `apps/bot/utilities/transformers.py` | ⬜ pending (Manual-Only: autocomplete) |
| 10-03 Task 1 | 10-03 | 2 | ADM-03 / D-04, D-10 | T-10-08, T-10-09, T-10-10 | All ephemeral; numeric `<@id>` mentions only; 404→zero via `except APIHTTPError` + `e.status == HTTPStatus.NOT_FOUND` | static (lint + type-check) + Manual-Only rendering | `uv run --directory apps/bot ruff check extensions/tournaments.py && uv run --directory apps/bot basedpyright extensions/tournaments.py` | `apps/bot/extensions/tournaments.py` | ⬜ pending (Manual-Only: /info card, paging, streak copy) |
| 10-03 Task 2 | 10-03 | 2 | ADM-03 / D-07 | T-10-07, T-10-11 | Authoritative Mod/Sensei `get_role` gate → UserFacingError; transformer-validated args | static (lint + type-check) + Manual-Only gate | `uv run --directory apps/bot ruff check extensions/tournaments.py && uv run --directory apps/bot basedpyright extensions/tournaments.py` | `apps/bot/extensions/tournaments.py` | ⬜ pending (Manual-Only: non-admin rejection) |
| 10-03 Task 3 | 10-03 | 2 | ADM-03 / D-04, D-07, D-13 | T-10-07, T-10-10 | reroll gate blocks non-admin (no API write); 404 APIHTTPError→0/0 mapping; empty-leaderboard short-circuit | unit (bot) | `uv run --directory apps/api pytest tests/bot/test_tournament_commands.py -v -p no:xdist` | `apps/bot/extensions/tournaments.py`, `apps/api/tests/bot/test_tournament_commands.py` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> Wave 0 RED tests are authored by 10-01 Task 1 (API streak) and 10-03 Task 3 (bot-side cog/paginator/gate).
> 10-02 Tasks 1-2 are pure glue/transformer code with no behavioral pytest harness (Discord interaction layer);
> their automatable gate is lint + type-check, and their interactive behavior is Manual-Only.

---

## Wave 0 Requirements

> The Wave-0 failing tests are authored INTO the EXISTING test files (no new standalone streak file —
> reconciled to match 10-01 Task 1 and 10-03 Task 3, which populate the files below).

- [ ] `apps/api/tests/services/test_tournament_service.py` — add `TestGetStreak` (10-01 Task 1): returns `TournamentStreakResponse` on a row; RAISES `StreakNotFoundError` when the repo returns None (mirrors `TestGetCategory` raising `CategoryNotFoundError`). MUST fail before 10-01 Task 2.
- [ ] `apps/api/tests/integration/test_tournaments_integration.py` — add `TestGetStreak` (10-01 Task 1): `GET /api/v3/tournaments/streaks/{user_id}` returns 200 + struct on a seeded row; 404 when absent (NOT zero — D-04 zero-mapping is bot-side); 401/403 without `tournaments:read`. Mirror `TestGetCategory`. MUST fail before 10-01 Task 2.
- [ ] `apps/api/tests/bot/test_tournament_commands.py` — new file (10-03 Task 3, path-load + stub pattern of `test_tournaments_handler.py`): `reroll_gate`, `reroll_dispatch`, `streak_zero` (404 `APIHTTPError` → 0/0 + encouraging copy), `leaderboard_empty`, `leaderboard_pagination`, `info_no_active_cycle`.

*Bot-side autocomplete + visual embed/paging rendering have no Discord interaction test harness — covered under Manual-Only.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `category` autocomplete returns live API categories | ADM-03 / D-09 | Requires Discord gateway + live API | Type partial category in `/tournament info` → autocomplete lists admin-created categories (≤25) |
| `/tournament info` rich card (map link, thumbnail, relative+absolute time) | criterion 1 / D-11, D-12 | Visual embed rendering in Discord | Run command on an active cycle → verify embed fields + `<t:..:R>`/`<t:..:F>` |
| Leaderboard pagination (page size 10) visual paging | criterion 2 / D-13 | Discord view button interaction | Run on a cycle with >10 submissions → verify paging buttons + 10-per-page |
| `/tournament streak` self-only zero-state visual copy | criterion 3 / D-04 | Discord interaction rendering | Run as a user with/without a streak record → verify zero-state encouraging line renders |
| `/tournament-reroll` non-admin rejection (live) | ADM-03 / D-07 | Bot-side role gate in a live guild | Invoke as a non-admin → expect `UserFacingError` rejection; invoke as Mod/Sensei → succeeds and shows the new map |

*The reroll gate logic, 404→zero streak mapping, and empty-leaderboard short-circuit ALSO have automated bot-side unit coverage (10-03 Task 3); the rows above are the live/visual confirmations. API streak endpoint behaviors have automated pytest verification (Wave 0).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (API) / Manual-Only entry (bot)
- [x] Sampling continuity: no 3 consecutive automatable tasks without automated verify
- [x] Wave 0 covers all MISSING references (existing service + integration files; new bot test file)
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

> `wave_0_complete: false` retained: the Wave-0 RED tests are AUTHORED by 10-01 Task 1 / 10-03 Task 3
> during execution and are not yet written on disk. Flip to `true` once those tasks land and the RED
> tests exist (failing as expected).

**Approval:** ready
</content>
