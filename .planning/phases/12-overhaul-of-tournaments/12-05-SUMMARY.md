---
phase: 12-overhaul-of-tournaments
plan: 05
subsystem: tournaments-bot-consumer
tags: [bot, discord, cv2, rollover, idempotency, allowed-mentions, conditional-render]
requires:
  - "12-02 (SDK TournamentRolloverEvent: edition_id/results/started; per-category TournamentCycleCompletedEvent/StartedEvent payload elements)"
  - "12-03 (outbox publishes ONE TournamentRolloverEvent on api.tournament.rollover keyed by tournament:rollover:{edition_id})"
  - "12-04 (api.get_active_edition; /tournament info reads stored edition ends_at)"
provides:
  - "_on_edition_rollover: single @queue_consumer(api.tournament.rollover, TournamentRolloverEvent, idempotent=True) replacing the _on_cycle_started + _on_cycle_completed pair (D-09)"
  - "ONE CV2 rollover card with conditional results/starting sections covering all three cases — normal / into-hiatus / out-of-hiatus (D-10)"
  - "Champion-role transfer (reused _transfer_champion_role verbatim) runs first and only when results present"
  - "Winner mentions by numeric <@id> only, gated by AllowedMentions(users=allow-list, everyone=False, roles=False); ping inside a ui.TextDisplay"
affects: []
tech-stack:
  added: []
  patterns:
    - "fuse the started/completed consumer pair into one edition-rollover consumer with conditional CV2 sections"
    - "champion transfers FIRST then a single channel.send LAST (Pitfall 5 ordering — role ops idempotent, duplicate send is visible spam)"
    - "numeric-id-only winner mentions; ping text inside ui.TextDisplay (CV2 LayoutView has no content=)"
    - "bot consumer-only: category/map fetched via self.bot.api on receipt, never reads Postgres"
key-files:
  created: []
  modified:
    - apps/bot/extensions/tournaments.py
    - apps/api/tests/bot/test_tournaments_handler.py
decisions:
  - "Single _on_edition_rollover consumer on api.tournament.rollover replaces the _on_cycle_started + _on_cycle_completed pair (D-09); deprecated TournamentCyclesStartedEvent/CompletedEvent imports dropped from the bot module"
  - "ONE CV2 card renders a results section iff event.results and a starting section iff event.started, covering normal / into-hiatus / out-of-hiatus (D-10); a both-empty event posts nothing (defensive)"
  - "Champion transfer iterates event.results before the card is sent and only when results are non-empty; _transfer_champion_role reused verbatim (strip-all-then-grant self-heal, A6)"
  - "Winners mentioned by numeric <@id> only, AllowedMentions(users=allow-list, everyone=False, roles=False); ping text lives in a ui.TextDisplay (T-12-11)"
metrics:
  duration: ~12m
  completed: 2026-06-01
  tasks: 1
  files: 2
---

# Phase 12 Plan 05: Bot Combined Rollover Consumer Summary

Collapsed the bot's `_on_cycle_started` + `_on_cycle_completed` consumer pair into
a single `_on_edition_rollover` handler on `api.tournament.rollover`, completing
the event path from DB → outbox → bot. The handler renders ONE Components V2
LayoutView card with conditional results/starting sections covering the three
rollover cases (normal / into-hiatus / out-of-hiatus), reuses the existing
champion-role transfer and AllowedMentions safety verbatim, and stays
consumer-only (all missing category/map data fetched via the API on receipt).

## What Was Built

- **`_on_edition_rollover`** (single `@queue_consumer("api.tournament.rollover",
  struct_type=TournamentRolloverEvent, idempotent=True)`): replaces both former
  consumers (D-09). Ordering preserved (Pitfall 5): champion transfers run FIRST,
  the single `channel.send` LAST.
  - **Champion transfer**, only when `event.results` is non-empty: iterates the
    per-category results, fetches each category via
    `self.bot.api.get_tournament_category`, and calls `_transfer_champion_role`
    (reused verbatim — strips all holders then grants the winner, self-healing A6).
  - **ONE CV2 card with conditional sections** (D-10): a `## 🏅 Results` block with a
    per-category podium + crowned winner is appended iff `event.results`; a
    `## 🏁 New Cycle` block with per-category map/difficulty/ends-at is appended iff
    `event.started`; sections separated by `ui.Separator()`; sent once. A both-empty
    event logs and returns without posting (defensive).
  - **Security (T-12-11):** winners aggregated and mentioned by numeric `<@id>` ONLY
    (never from free-text standings names); the ping text lives INSIDE a
    `ui.TextDisplay` (CV2 LayoutView `send` accepts no `content=` — MEMORY.md); the
    send uses `AllowedMentions(users=[Object(id=w)...], everyone=False, roles=False)`.
  - **Consumer-only (T-12-13):** category name + `champion_role_id` and map
    difficulty are fetched via `self.bot.api.*` on receipt; the bot never reads
    Postgres.
- **Removed** the deprecated `TournamentCyclesStartedEvent` / `TournamentCyclesCompletedEvent`
  imports from the bot module; the module docstring now describes the single
  rollover consumer.
- **Tests** (`test_tournaments_handler.py`): added the three conditional render
  cases plus a both-empty defensive case and an empty-standings case under the
  `-k rollover` selector; converted the four champion-transfer tests
  (strip-all-then-grant, vacant-no-winner, no-role-configured, member-left-guild,
  stagger) to drive `_on_edition_rollover` with `TournamentRolloverEvent(results=[...],
  started=[])`. The real-`@queue_consumer`-wrapper idempotency test is unchanged
  (it tests the wrapper, not the rollover handler).

## Deviations from Plan

None — plan executed exactly as written. The linter (ruff format) wrapped one long
`log.info` call onto multiple lines; no behavioral change.

## Deferred Issues (out of scope — pre-existing, not caused by this plan)

The TRUE full suite (`pytest -n 4 --no-testmon`) reports **7 failed / 1801 passed /
2 skipped / 2 xfailed**. All 7 failures are the deferred-by-design set documented in
the 12-03 and 12-04 SUMMARYs (`deferred-items.md`), none are in this plan's
`files_modified`, and none are regressions from the bot handler change:

- `tests/repository/tournaments/test_cycle_transitions.py` (5) — invoke the removed
  `tournaments.process_cycle_transitions()` and the dropped `cat.cycle_frequency`
  column (`UndefinedColumnError: column cat.cycle_frequency does not exist`). Edition
  behavior is covered by `test_edition_transitions.py`. Deferred-by-design (12-01 doc).
- `tests/repository/tournaments/test_lifecycle_control.py` (2) — per-category repo
  shims now return the config singleton (dict), not None. Deferred-by-design.

The 12-04 SUMMARY explicitly predicted "the 7 remaining = deferred-by-design
`test_cycle_transitions.py` 5 + `test_lifecycle_control.py` 2; no regressions" — this
run confirms exactly that count, so this plan introduced zero new failures.

## Authentication Gates

None.

## Verification

- Targeted (plan verification): `pytest tests/bot/test_tournaments_handler.py -k "rollover"
  --no-testmon -p no:xdist` → **5 passed, 11 deselected**.
- Full handler file: `pytest tests/bot/test_tournaments_handler.py --no-testmon -p no:xdist`
  → **16 passed** (rollover cases + converted champion-transfer + idempotency).
- Source gate: `grep "api.tournament.rollover\|AllowedMentions"` present;
  `_on_cycle_started` / `_on_cycle_completed` / `TournamentCyclesStartedEvent` /
  `TournamentCyclesCompletedEvent` no longer appear in `apps/bot/extensions/tournaments.py`.
- Lint: `just lint-bot` clean (ruff format + ruff check + basedpyright 0 errors/0 warnings).
- Wave-merge full suite: `pytest -n 4 --no-testmon` → 7 failed (all deferred-by-design,
  none regressions) / 1801 passed / 2 skipped / 2 xfailed.

## Threat Flags

None — no new security surface beyond the plan's threat register. T-12-11
(mention-injection) mitigated: numeric `<@id>` mentions only + `AllowedMentions`
allow-list + ping inside `ui.TextDisplay`. T-12-12 (duplicate rollover) mitigated:
`@queue_consumer(idempotent=True)` claims on `tournament:rollover:{edition_id}` +
strip-all-then-grant idempotent end state. T-12-13 (bot writing Postgres) mitigated:
handler reads via `self.bot.api.*` and performs Discord-only actions. T-12-SC
(installs) not applicable — zero new packages.

## Self-Check: PASSED
