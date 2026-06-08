---
phase: 09-bot-queue-consumers-announcements
plan: 02
subsystem: bot-tournament-announcements
tags: [bot, rabbitmq, queue-consumer, discord, embeds, champion-role, wave-2]
requires:
  - "config.channels.tournament.announcements (Plan 09-01, D-01)"
  - "APIService.get_tournament_category(category_id) (Plan 09-01, D-08)"
  - "APIService.get_map(code=...) → MapModel (existing)"
  - "genjishimada_sdk.tournaments TournamentCycleStartedEvent / TournamentCycleCompletedEvent (Phase 7)"
  - "@queue_consumer(idempotent=True) wrapper + RabbitHandler public-attr scan (existing bot infra)"
provides:
  - "apps/bot/extensions/tournaments.py — TournamentHandler with two cycle-scoped-idempotent consumers"
  - "DSC-01 new-cycle embed; DSC-02 results embed; DSC-03 + RWD-03 champion role transfer"
  - "public bot.tournaments property on core.Genji (so the consumers register at startup)"
affects:
  - "Phase 10 (slash commands) builds on the same tournament announcement channel + category data"
tech-stack:
  added: []
  patterns:
    - "BaseHandler subclass + @queue_consumer(idempotent=True) consumer (mirrors CompletionHandler)"
    - "Strip-all-then-grant role transfer with asyncio.sleep stagger (self-healing, D-04/D-05)"
    - "Role transfer FIRST, single channel.send LAST (Pitfall 5 retry-safety ordering)"
    - "Numeric <@user_id> mentions + AllowedMentions(everyone=False, roles=False) (mention-injection mitigation)"
    - "Unit-test bot handler by path-loading the module with lightweight bot-internal stubs"
key-files:
  created:
    - apps/bot/extensions/tournaments.py
  modified:
    - apps/bot/core/genji.py
    - apps/api/tests/bot/test_tournaments_handler.py
decisions:
  - "D-02/D-07: new-cycle embed sources difficulty/category/banner via get_map + get_tournament_category on receipt"
  - "D-03: results embed deliberately omits any XP line (XP delivered via api.xp.grant separately)"
  - "D-04/D-05: champion role stripped from ALL holders then granted to winner, or left vacant when no winner"
  - "D-06: champion transfer folded into the single results embed (one message per cycle)"
  - "_ROLE_OP_DELAY = 1.0s courtesy stagger (A1); discord.py auto-handles 429s as the safety net"
  - "A3: workshop-code link assumed https://workshop.codes/{code}"
metrics:
  duration: 18min
  completed: 2026-05-30
---

# Phase 9 Plan 02: Tournament Announcement Handler Summary

Built `apps/bot/extensions/tournaments.py` — a `TournamentHandler(BaseHandler)` with two cycle-scoped-idempotent queue consumers that post the DSC-01 new-cycle embed and the DSC-02 results embed (Top-3 podium + winner ping, no XP line per D-03), fold in the DSC-03/RWD-03 champion-role transfer (strip-all-then-grant, staggered, role-first/send-last), and wired it as a PUBLIC `bot.tournaments` property on `core.Genji` so `RabbitHandler` registers the consumers. The six Wave-0 xfail handler stubs are now nine green tests.

## What Was Built

**Task 1 — TournamentHandler + cycle_started embed (commits b0d024e RED, 19e62ef GREEN)**
- New `apps/bot/extensions/tournaments.py`: `TournamentHandler(BaseHandler)` with `announcement_channel: TextChannel` and `_resolve_channels()` reading `self.bot.config.channels.tournament.announcements`.
- `_on_cycle_started` decorated `@queue_consumer("api.tournament.cycle_started", struct_type=TournamentCycleStartedEvent, idempotent=True)`: fetches category (`get_tournament_category`) + map (`get_map(code=...)`, NOT `/partial`), builds a D-02 embed (map name, clickable `workshop.codes` link + raw code, Difficulty/Category fields, `format_dt(ends_at, "R")`, banner thumbnail when present), posts once.
- `_on_cycle_completed` registered as a logged stub (filled in Task 2) so both queues register.
- Public `async def setup(bot): bot.tournaments = TournamentHandler(bot)` (Pitfall 1).
- Module-level `%s`-style logging with `[→]/[✓]/[!]` markers; `TYPE_CHECKING` import of `core` (no circular import).

**Task 2 — Champion role transfer + results embed (commit f19cc00)**
- Filled `_on_cycle_completed`: fetches category, then `_transfer_champion_role` runs FIRST (Pitfall 5), single `announcement_channel.send` LAST.
- `_transfer_champion_role`: `guild.get_role(category.champion_role_id)`; strips role from ALL `role.members` (D-04 self-healing) with `await asyncio.sleep(_ROLE_OP_DELAY)` between edits (Pitfall 2); grants to `guild.get_member(winner_user_id)` when present; leaves vacant when `winner_user_id is None` (D-05); winner-left-guild (`get_member` None) logged `[!]` and skipped, not crashed (Pitfall 3). Each op passes a `reason`.
- Results embed: Top-3 podium with numeric `<@user_id>` mentions (never the free-text `name`), `"No submissions"` fallback, a "crowned Champion of {category}" field + winner ping `content` when a winner exists, `AllowedMentions(users=[winner] | [], everyone=False, roles=False)`. No XP line (D-03).

**Task 3 — Public bot.tournaments wiring + idempotency test (commit 152f0ee)**
- `apps/bot/core/genji.py`: `from extensions.tournaments import TournamentHandler`, `_tournament_manager: TournamentHandler` class attr, public `@property tournaments` + `@tournaments.setter` pair (mirrors `completions`).
- Idempotency test exercises the REAL `queue_consumer` wrapper (loaded by path): duplicate `message_id` (claim returns `claimed=False`) skips the handler body; a handler exception with a claimed message awaits `delete_claimed_idempotency`.

## Verification Results

- `pytest tests/bot/test_tournaments_handler.py --no-testmon -p no:xdist` → **9 passed, 0 xfail**.
- `pytest tests/bot/ --no-testmon -p no:xdist` → **12 passed** (3 config + 9 handler).
- `grep -v '^#' apps/bot/extensions/tournaments.py | grep -ic "xp awarded"` → **0**.
- `dir(Genji)` includes `tournaments` (public) → **True**.
- Runtime import: `core.genji` imports cleanly (no circular import); both consumers expose `_queue_name` = `api.tournament.cycle_started` / `api.tournament.cycle_completed` with `_idempotent=True`.
- `ruff format` + `ruff check` on `tournaments.py` + `core/genji.py` → clean; `basedpyright` → 0 errors, 0 warnings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test fakes imported via `from conftest import …` resolved to the wrong conftest**
- **Found during:** Task 2 (champion/results tests raised `ImportError: cannot import name 'FakeGuild' from 'conftest'`).
- **Issue:** A bare `import conftest` under pytest's rootdir resolves to the top-level `apps/api/conftest.py`, not the bot package's `tests/bot/conftest.py` where the `FakeGuild/FakeRole/FakeMember` trio lives.
- **Fix:** Added a `_load_bot_conftest()` helper that loads `tests/bot/conftest.py` by file path and binds `FakeGuild/FakeMember/FakeRole` at module scope; removed the per-test local imports.
- **Files modified:** `apps/api/tests/bot/test_tournaments_handler.py`
- **Commit:** f19cc00

**2. [Rule 2 - Critical] Winner-left-guild guard added beyond the explicit cycle_started/results stubs**
- **Found during:** Task 2.
- **Issue:** Pitfall 3 requires the handler not to crash when `winner_user_id` is set but `get_member` returns None (member left between submission and finalization) — crashing would DLQ a valid event.
- **Fix:** `_transfer_champion_role` logs `[!]` and returns None (role left vacant) instead of calling `add_roles` on None; added `test_champion_member_left_guild_does_not_crash` asserting the strip still happens and the results embed still posts.
- **Files modified:** `apps/bot/extensions/tournaments.py`, `apps/api/tests/bot/test_tournaments_handler.py`
- **Commit:** f19cc00

**3. [Plan-intent clarification] Docstring reworded to satisfy the literal grep acceptance check**
- The acceptance criterion `grep -ic "xp awarded" == 0` initially matched a docstring sentence ("No \"XP awarded\" line is added"). Reworded the docstring to "deliberately omits any experience-points line" — preserves the D-03 intent while keeping the grep at 0. The embed code itself never contained any XP string.

## TDD Gate Compliance

Plan type is `execute`; Tasks 1 and 2 carry `tdd="true"`. RED gate: commit `b0d024e` (`test(09-02): … (RED)`) replaced the xfail stubs with real failing tests (collection error — module absent — then 5 failures for Task 2). GREEN gates: `19e62ef` (cycle_started) and `f19cc00` (results/champion/stagger). Task 3 is non-TDD wiring; its idempotency test was authored in the RED commit and passed once the real wrapper was exercised. No REFACTOR commit was needed.

## Known Stubs

None. The `_on_cycle_completed` Task-1 logged stub was fully implemented in Task 2; all nine handler tests are green with zero remaining xfail.

## Self-Check: PASSED

- `apps/bot/extensions/tournaments.py` — FOUND.
- `apps/bot/core/genji.py` — FOUND (public `tournaments` property).
- `apps/api/tests/bot/test_tournaments_handler.py` — FOUND (9 passing tests).
- Commits b0d024e, 19e62ef, f19cc00, 152f0ee — all present in git history (verified).
