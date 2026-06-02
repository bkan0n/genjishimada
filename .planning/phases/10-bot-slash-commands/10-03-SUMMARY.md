---
phase: 10-bot-slash-commands
plan: 03
subsystem: bot
tags: [tournaments, discord, app_commands, group_cog, paginator, admin-gate, ephemeral]
requires:
  - phase: 10-01-streak-read-endpoint
    provides: "GET /tournaments/streaks/{user_id} (404s on absent) backing /tournament streak"
  - phase: 10-02-apiservice-wrappers-transformer
    provides: "Six tournament APIService wrappers + CategoryTransformer composed by this cog"
provides:
  - "TournamentCommandCog (/tournament GroupCog: info, leaderboard, streak)"
  - "TournamentRerollCog (flat /tournament-reroll admin command, bot-side Mod/Sensei gate)"
  - "TournamentLeaderboardPaginator (StaticPaginatorView, 10/page, <@id> rows)"
affects: []
tech-stack:
  added: []
  patterns:
    - "GroupCog + flat command split: player subcommands in a GroupCog, the admin command kept FLAT (default_member_permissions applies at the top-level command/group and cannot mix open + locked subcommands)"
    - "Bot owns the 404->zero-state mapping: except APIHTTPError + e.status == HTTPStatus.NOT_FOUND maps to 0/0, any other status re-raised"
    - "Empty StaticPaginatorView short-circuit BEFORE construction (zero pages -> modulo-by-zero on navigation)"
    - "Authoritative admin gate is the bot-side itx.user.get_role(mod/sensei) check raising UserFacingError; default_member_permissions is a UI hint only"
key-files:
  created:
    - apps/api/tests/bot/test_tournament_commands.py
  modified:
    - apps/bot/extensions/tournaments.py
    - apps/api/tests/bot/test_tournaments_handler.py
decisions:
  - "TournamentLeaderboardPaginator parametrized StaticPaginatorView[Any] (the T bound is FormattableProtocol/to_format_dict, which the leaderboard struct lacks); build_page_body is overridden and never calls to_format_dict, so Any is sound and avoids polluting the SDK struct"
  - "Flat /tournament-reroll lives on a separate BaseCog (TournamentRerollCog), not the GroupCog (D-06)"
  - "Both bot test files share a real-utilities loader with sys.modules snapshot/restore — the new cog imports (utilities.transformers/paginator/errors) made the handler test's empty-utilities stub strategy untenable; loading the real graph (which imports cleanly) + restoring afterward keeps sibling tests isolated"
metrics:
  duration: 7min
  completed: 2026-05-30
requirements: [ADM-03]
---

# Phase 10 Plan 03: Tournament Slash Commands Summary

The visible feature of Phase 10 (and ADM-03): a guild-scoped `/tournament` GroupCog (`info`, `leaderboard`, `streak`) plus a separate flat `/tournament-reroll` admin command, all in `apps/bot/extensions/tournaments.py` alongside the Phase-9 `TournamentHandler` — reusing its embed styling and the `StaticPaginatorView`, with the authoritative admin control as a bot-side Mod/Sensei role gate and the streak 404→zero-state mapping owned by the bot.

## What Was Built

- **`TournamentCommandCog(commands.GroupCog, group_name="tournament")`** (`@app_commands.guilds(...)`), all three subcommands deferring `ephemeral=True` first (D-10):
  - **`info`** (D-08/D-11/D-12) — fetches the category + active cycle (`list_tournament_cycles(status="active", ...)`), short-circuits "No active cycle…" when empty, else builds a rich embed (map workshop link, difficulty, category, banner thumbnail) and computes `ends_at = started_at + timedelta(7 weekly / 14 biweekly)` locally (OQ1), rendered as `format_dt(R)` + `format_dt(F)`. Map metadata via `get_map(code=...)`.
  - **`leaderboard`** (D-16) — resolves the active cycle, fetches entries, **short-circuits the empty case BEFORE constructing the paginator** (Pitfall 1: a zero-page `StaticPaginatorView` modulo-by-zeroes on navigation), else renders `TournamentLeaderboardPaginator` (10/page).
  - **`streak`** (D-02/D-03/D-04) — self-only (`itx.user.id`, no user arg); wraps `get_tournament_streak` in `except APIHTTPError`, mapping `e.status == HTTPStatus.NOT_FOUND` to current 0 / max 0 with "Submit in a cycle to start your streak!" and re-raising any other status.
- **`TournamentLeaderboardPaginator(StaticPaginatorView[Any])`** — pages built eagerly in `__init__` (page_size=10); rows render numeric `<@user_id>` mentions only (OQ2 / T-10-10 mention-injection mitigation), never `entry.name`.
- **`TournamentRerollCog(BaseCog)`** — flat `/tournament-reroll` (`@app_commands.default_permissions(manage_guild=True)`, a UI hint only). Body defers ephemerally, then the **authoritative** Mod/Sensei `itx.user.get_role(...)` gate raising `UserFacingError` (D-07 / T-10-07); dispatches `reroll_next_cycle(category)` when `code is None` (D-14) or `choose_next_cycle(category, TournamentChooseMapRequest(map_code=code))` with a code (D-15); replies with the new map embed.
- **Extended `setup()`** — keeps `bot.tournaments = TournamentHandler(bot)` and adds `await bot.add_cog(TournamentCommandCog(bot))` and `await bot.add_cog(TournamentRerollCog(bot))` as separate lines (Pitfall 7). Staying in `tournaments.py` preserves the EXTENSIONS sort that loads before `rabbit.py`.
- **`apps/api/tests/bot/test_tournament_commands.py`** — 11 tests covering the six required `-k`-selectable behaviors plus extras (real-record streak, explicit-code dispatch, mention-rendering, info-card render).

## How It Works

The bot holds one full-scope API key, so `tournaments:write` does NOT restrict the Discord audience — the only real control on reroll is the inline role check (verified by `reroll_gate` asserting neither write wrapper is called for a non-admin). The cycles list carries no `ends_at`, so `info` computes it locally from the category cadence. The streak endpoint deliberately 404s on an absent record; the bot translates that single status to the zero-state card while letting any other HTTP error surface.

## TDD Gate Compliance

Task 3 is `tdd="true"`. The cog implementation (Tasks 1-2) was committed before the tests, so the RED→GREEN ordering is collapsed: the `test(10-03)` commit's tests passed immediately against the already-committed `feat(10-03)` implementation. All six required behaviors are present and green; no separate failing-first commit exists for this plan's tests.

## Verification

- `pytest tests/bot/test_tournament_commands.py -v -p no:xdist` — 11 passed
- `pytest tests/bot/ --no-testmon -p no:xdist` — 24 passed (handler + command + config tests together, both orderings)
- Per-wave merge: `pytest tests/bot/test_tournament_commands.py tests/integration/test_tournaments_integration.py tests/services/test_tournament_service.py --no-testmon -p no:xdist` — 81 passed
- `ruff check extensions/tournaments.py` — clean; `basedpyright extensions/tournaments.py` — 0 errors
- Manual-Only (VALIDATION.md): live admin gate, category autocomplete, `/info` rich card, leaderboard paging/empty, streak zero-state — confirmable only in the dev guild.

## Task Commits

1. **Task 1 + 2: cog source** — `dcf7a27` (feat) — `/tournament` GroupCog (info/leaderboard/streak), flat `/tournament-reroll`, paginator, extended setup(). Tasks 1 and 2 both edit only `tournaments.py`; their additions are inseparable in a single file, so they share one source commit.
3. **Task 3: bot-side tests** — `ffa9eae` (test) — six behaviors + extras; updated the sibling handler test's module loader.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `TournamentLeaderboardPaginator` generic parameter**
- **Found during:** Task 1 (basedpyright)
- **Issue:** `StaticPaginatorView[T]` bounds `T` to `FormattableProtocol` (requires `to_format_dict`), which `TournamentLeaderboardEntryResponse` lacks → type error.
- **Fix:** Parametrized as `StaticPaginatorView[Any]`. `build_page_body` is overridden and never calls `to_format_dict`, so the bound is irrelevant at runtime; this avoids adding a `to_format_dict` to the SDK struct.
- **Files modified:** `apps/bot/extensions/tournaments.py`
- **Commit:** `dcf7a27`

**2. [Rule 3 - Blocking] Sibling handler test broke under the new cog imports**
- **Found during:** Task 3 (running `tests/bot/` together)
- **Issue:** Plan 10-03 added `utilities.transformers`/`paginator`/`errors` + `discord.ext.commands` imports to `tournaments.py`. `test_tournaments_handler.py` loaded the module with empty `utilities` stubs that could not satisfy these imports, so collection failed.
- **Fix:** Switched both bot test files to a shared real-utilities loader that snapshots/evicts the `utilities`/`extensions` `sys.modules` trees, prepends apps/bot to `sys.path`, stubs ONLY `extensions._queue_registry` (the handler tests need the unwrapped `queue_consumer`), loads `tournaments.py`, then restores the snapshot so sibling tests stay isolated. Both run orders pass.
- **Files modified:** `apps/api/tests/bot/test_tournaments_handler.py`, `apps/api/tests/bot/test_tournament_commands.py`
- **Commit:** `ffa9eae`

### Combined commit for Tasks 1 + 2

Tasks 1 and 2 were committed together (`dcf7a27`) because both modify only `apps/bot/extensions/tournaments.py` and their additions are interleaved in one coherent module edit; splitting them would require partial-file reverts. Task 3 (tests) is a separate commit per the plan.

## Known Stubs

None. All commands wire live API data; empty/missing states are intentional friendly messages (D-16), not stubs.

## Self-Check: PASSED

- `apps/bot/extensions/tournaments.py` — FOUND (TournamentCommandCog, TournamentRerollCog, TournamentLeaderboardPaginator)
- `apps/api/tests/bot/test_tournament_commands.py` — FOUND (11 tests, six required behaviors)
- Commit `dcf7a27` (feat) — present in git log
- Commit `ffa9eae` (test) — present in git log

---
*Phase: 10-bot-slash-commands*
*Completed: 2026-05-30*
