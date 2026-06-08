---
phase: 10-bot-slash-commands
verified: 2026-05-30T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run /tournament info in the dev guild on an active cycle"
    expected: "Rich embed shows map workshop link, difficulty, category, thumbnail, relative+absolute end time (format_dt R + F)"
    why_human: "Visual embed rendering requires a live Discord gateway; format_dt output is Discord client-side"
  - test: "Run /tournament leaderboard on a cycle with >10 submissions"
    expected: "Pages of exactly 10 entries with navigation buttons; each row is numeric <@user_id> mention, not a name"
    why_human: "StaticPaginatorView button interaction requires a live Discord interaction runtime"
  - test: "Run /tournament streak as a user with no streak record, then as one with a record"
    expected: "No-record case shows 'Submit in a cycle to start your streak!' with current 0 / max 0; with-record case shows actual values without the zero-state copy"
    why_human: "Ephemeral embed rendering visible only to the invoker in a live guild"
  - test: "Run /tournament-reroll as a non-Mod/non-Sensei member"
    expected: "UserFacingError rejection message shown; no API write occurs"
    why_human: "Live Discord role gate requires an actual guild member with/without the relevant roles"
  - test: "Run /tournament-reroll as a Mod/Sensei member (with and without the optional code arg)"
    expected: "Without code: random reroll succeeds and embed shows new map. With code: explicit map selected and embed shows that map."
    why_human: "End-to-end reroll requires a live guild, a live API, and a pending next-cycle to reroll"
  - test: "Type a partial category name in /tournament info category arg"
    expected: "Autocomplete lists up to 25 live admin-created categories filtered by case-fold substring"
    why_human: "CategoryTransformer autocomplete requires Discord gateway + live API list_tournament_categories call"
---

# Phase 10: Bot Slash Commands Verification Report

**Phase Goal:** Players and admins can interact with the tournament system through Discord slash commands
**Verified:** 2026-05-30
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Players can view the current active cycle info via a slash command | VERIFIED | `TournamentCommandCog.info` at `tournaments.py:292-340` — fetches category + active cycle, builds embed with map link, difficulty, category, local ends_at computation, thumbnail; guild-scoped GroupCog with `@app_commands.command(name="info")` |
| 2 | Players can view the current cycle leaderboard via a slash command | VERIFIED | `TournamentCommandCog.leaderboard` at `tournaments.py:342-376` — resolves active cycle, fetches leaderboard, short-circuits empty case before paginator construction, renders `TournamentLeaderboardPaginator` (page_size=10, `<@user_id>` mentions only) |
| 3 | Players can check their participation streak via a slash command | VERIFIED | `TournamentCommandCog.streak` at `tournaments.py:378-411` — self-only (passes `itx.user.id`), wraps `get_tournament_streak` in `except APIHTTPError`, maps `e.status == HTTPStatus.NOT_FOUND` to 0/0 + "Submit in a cycle to start your streak!" |
| 4 | Admins can trigger a map reroll via a slash command (ADM-03) | VERIFIED | `TournamentRerollCog.tournament_reroll` at `tournaments.py:422-466` — flat `/tournament-reroll` command (separate from GroupCog), bot-side `get_role(mod/sensei)` gate raising `UserFacingError`, dispatches `reroll_next_cycle` (no code) or `choose_next_cycle` (with code) |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `apps/api/services/exceptions/tournaments.py` | `StreakNotFoundError(TournamentsError)` | VERIFIED | Line 143: `class StreakNotFoundError(TournamentsError)` with `__init__(self, user_id: int)`, docstring "User tournament streak record does not exist." |
| `apps/api/services/tournament_service.py` | `get_streak(user_id) -> TournamentStreakResponse` raising `StreakNotFoundError` | VERIFIED | Lines 159-174: fetches via `_tournament_repo.fetch_streak`, raises `StreakNotFoundError(user_id)` when None, else `msgspec.convert(row, TournamentStreakResponse)` — exact mirror of `get_category` |
| `apps/api/routes/v3/tournaments.py` | `GET /streaks/{user_id:int}` with `tournaments:read` scope | VERIFIED | Lines 192-221: `@litestar.get(path="/streaks/{user_id:int}")`, `opt={"required_scopes": {"tournaments:read"}}`, catches `StreakNotFoundError` → `CustomHTTPException(HTTP_404_NOT_FOUND)` |
| `apps/bot/extensions/api_service.py` | Six tournament wrappers including `get_tournament_streak`, `reroll_next_cycle` (POST), `choose_next_cycle` (PATCH) | VERIFIED | Lines 1683-1767: all six sync `def` wrappers present; POST verb on reroll (line 1751), PATCH verb on choose (line 1766); six SDK structs imported at lines 102-107 |
| `apps/bot/utilities/transformers.py` | `CategoryTransformer` with autocomplete + transform | VERIFIED | Lines 255-292: digit fast-path `transform`, case-fold name resolution with `UserFacingError` on miss, `autocomplete` capped at `[:25]` (line 292), calls `list_tournament_categories` (lines 271, 288) |
| `apps/bot/extensions/tournaments.py` | `TournamentCommandCog` (GroupCog "tournament"), `TournamentRerollCog`, `TournamentLeaderboardPaginator`, extended `setup()` | VERIFIED | All classes present at lines 242, 275, 414; `setup()` at lines 469-480 registers both cogs as separate lines, preserves `bot.tournaments = TournamentHandler(bot)` |
| `apps/api/tests/bot/test_tournament_commands.py` | 11 bot-side unit tests covering gate/dispatch/streak-zero/leaderboard/info behaviors | VERIFIED | 11 tests collected and all pass (`11 passed in 2.60s` with `--no-testmon`) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tournaments.py (route)` | `TournamentService.get_streak` | `await tournament_service.get_streak(user_id)` | WIRED | Line 216 in routes/v3/tournaments.py |
| `tournament_service.py` | `TournamentRepository.fetch_streak` | `await self._tournament_repo.fetch_streak(user_id)` | WIRED | Line 171 in tournament_service.py |
| `tournaments.py (route)` | `StreakNotFoundError -> CustomHTTPException(404)` | `except StreakNotFoundError as e: raise CustomHTTPException(HTTP_404_NOT_FOUND, ...)` | WIRED | Lines 217-220 in routes/v3/tournaments.py |
| `transformers.py (CategoryTransformer)` | `APIService.list_tournament_categories` | `itx.client.api.list_tournament_categories()` | WIRED | Lines 271 and 288 in transformers.py |
| `tournaments.py (TournamentCommandCog)` | `CategoryTransformer` on info/leaderboard | `app_commands.Transform[int, transformers.CategoryTransformer]` | WIRED | Lines 296 and 349 in tournaments.py |
| `tournaments.py (TournamentRerollCog)` | `config.roles.admin.mod / .sensei` | `itx.user.get_role(itx.client.config.roles.admin.mod/sensei)` | WIRED | Lines 446-447 in tournaments.py |
| `tournaments.py (TournamentRerollCog)` | `APIService.reroll_next_cycle / choose_next_cycle` | code-is-None dispatch | WIRED | Lines 456-458 in tournaments.py |
| `tournaments.py setup()` | `TournamentCommandCog` + `TournamentRerollCog` | `await bot.add_cog(...)` | WIRED | Lines 479-480 in tournaments.py; `bot.tournaments` on line 478 preserved separately |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `TournamentCommandCog.info` | `category_data`, `active`, `map_data` | `api.get_tournament_category`, `api.list_tournament_cycles`, `api.get_map` | Yes — live API calls via `APIService._request` over HTTP | FLOWING |
| `TournamentCommandCog.leaderboard` | `entries` | `api.get_tournament_leaderboard(active.id)` | Yes — live API endpoint returning leaderboard rows | FLOWING |
| `TournamentCommandCog.streak` | `streak_data` | `api.get_tournament_streak(itx.user.id)` | Yes — calls GET /tournaments/streaks/{user_id}; 404 mapped to 0/0 bot-side | FLOWING |
| `TournamentRerollCog.tournament_reroll` | `result` | `api.reroll_next_cycle` or `api.choose_next_cycle` | Yes — POST/PATCH endpoints mutate DB and return `TournamentNextCycleResponse` | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Service raises StreakNotFoundError on absent row | `pytest tests/services/test_tournament_service.py -k GetStreak` | 2 passed | PASS |
| Integration: 200 on seeded row, 404 absent, 401 no-auth | `pytest tests/integration/test_tournaments_integration.py -k GetStreak` | 3 passed | PASS |
| Bot: reroll gate rejects non-admin, no API write | `pytest tests/bot/test_tournament_commands.py --no-testmon` | 11 passed | PASS |
| Bot: 404 APIHTTPError → 0/0 zero-state + encouraging copy | same run | 11 passed | PASS |
| Bot: empty leaderboard short-circuits before paginator | same run | 11 passed | PASS |
| Bot: pagination 25 entries → 3 pages of 10/10/5 | same run | 11 passed | PASS |

### Probe Execution

No probes declared or conventional probe scripts found for this phase. Step 7c: SKIPPED (no probe scripts).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ADM-03 | 10-01, 10-02, 10-03 | Admin Discord slash commands for tournament actions | SATISFIED | `/tournament-reroll` command exists with Mod/Sensei gate; dispatches reroll or choose-map; reroll_gate unit test asserts non-admin rejection with no API write |

REQUIREMENTS.md line 109 shows `ADM-03 | Phase 10 | Complete` — consistent with phase delivery.

### Anti-Patterns Found

No `TBD`, `FIXME`, or `XXX` markers found in any of the five phase-modified source files (`tournaments.py`, `api_service.py`, `transformers.py`, `routes/v3/tournaments.py`, `services/tournament_service.py`).

No stub patterns (empty returns, placeholder text, hardcoded-empty arrays flowing to rendering) found. Empty-state messages like "No active cycle…" and "No submissions yet — be the first!" are intentional friendly UX messages (D-16), not stubs — they are conditional on actual API data returning empty.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | — | — | — |

### Human Verification Required

The following behaviors require a live Discord gateway and cannot be verified programmatically. These items are pre-documented in `10-VALIDATION.md` as Manual-Only; automated coverage for their underlying logic (gate, zero-state mapping, empty-leaderboard short-circuit, pagination boundary) is provided by the 11 bot-side unit tests.

#### 1. /tournament info rich card rendering

**Test:** Invoke `/tournament info` on an active cycle in the dev guild.
**Expected:** Embed shows map name as a clickable workshop.codes link, difficulty field, category field, relative timestamp (`<t:..:R>`) and absolute timestamp (`<t:..:F>`) in the Ends field, and thumbnail from the map banner URL.
**Why human:** Visual embed rendering and Discord `format_dt` output are only verifiable in a live Discord client.

#### 2. /tournament leaderboard visual pagination

**Test:** Invoke `/tournament leaderboard` on a cycle with more than 10 submissions.
**Expected:** Pages of exactly 10 entries with Previous/Next buttons; each row shows `#rank <@user_id> — Xs` using numeric mentions only (no player names in mention position).
**Why human:** StaticPaginatorView navigation buttons require a live Discord interaction runtime; visual pagination is not exercisable in unit tests.

#### 3. /tournament streak zero-state visual copy

**Test:** Invoke `/tournament streak` as a user with no streak record, then as one with a record.
**Expected:** No-record: ephemeral embed shows "Current Streak: 0", "Max Streak: 0", description "Submit in a cycle to start your streak!". With-record: shows actual values, no zero-state description.
**Why human:** Ephemeral embed display visible only to the invoker in a live guild.

#### 4. /tournament-reroll non-admin rejection (live)

**Test:** Invoke `/tournament-reroll` as a Discord member who has neither the Mod nor Sensei role.
**Expected:** UserFacingError rejection message displayed; no API mutation occurs.
**Why human:** Bot-side role gate requires real guild member objects with actual role assignments; unit test exercises the same code path but with mocked `get_role`.

#### 5. /tournament-reroll admin success (random and explicit)

**Test:** Invoke `/tournament-reroll` as a Mod/Sensei member without a code arg, then again with a valid map code.
**Expected:** Without code: random reroll succeeds, embed shows newly-selected map. With code: explicit map selected and embed shows that map.
**Why human:** End-to-end requires live API with a pending next-cycle record, live guild, and live bot session.

#### 6. CategoryTransformer live autocomplete

**Test:** Type a partial category name into the `category` arg of `/tournament info` in the dev guild.
**Expected:** Autocomplete dropdown populates with up to 25 admin-created categories from the live API, filtered by case-fold substring match.
**Why human:** Discord autocomplete interaction requires a live gateway connection; `list_tournament_categories` API call requires a running API server.

### Gaps Summary

No automated gaps. All four ROADMAP success criteria are verified against actual code: the streak API endpoint (plan 10-01), the bot wrappers and CategoryTransformer (plan 10-02), and the four slash commands with their complete wiring (plan 10-03) all exist, are substantive, are properly connected, and have passing tests.

Six items remain in the human verification queue per the VALIDATION.md contract established before execution. These are the expected Manual-Only confirmation steps for visual/Discord-gateway behaviors that cannot be exercised without a live bot session.

---

_Verified: 2026-05-30_
_Verifier: Claude (gsd-verifier)_
