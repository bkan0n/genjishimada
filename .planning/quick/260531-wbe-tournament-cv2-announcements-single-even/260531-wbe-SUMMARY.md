---
phase: quick-260531-wbe
plan: 01
subsystem: tournaments
tags: [tournaments, rabbitmq, components-v2, outbox, discord]
requires:
  - tournaments.pending_transitions outbox (Phase 7)
  - TournamentRewardService cycle-end hooks (Phase 8)
  - TournamentHandler + CV2 idiom (Phase 9 / 11)
provides:
  - TournamentCyclesStartedEvent / TournamentCyclesCompletedEvent batch structs
  - grouped (event_type, created_at) outbox publish on plural routing keys
  - CV2 batch announcement consumers + CV2 command cards
affects:
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - apps/api/services/tournament_outbox_service.py
  - apps/bot/extensions/tournaments.py
tech-stack:
  added: []
  patterns:
    - "Outbox rows grouped by (event_type, created_at) into ONE batch event per rotation"
    - "Rotation-scoped idempotency key tournament:{event_type}:{created_at_iso}"
    - "CV2 LayoutView with per-category Separator sections + static hero MediaGallery"
    - "LayoutView send overload forbids content= → winners ping moved inside the card, gated by AllowedMentions allow-list"
key-files:
  created: []
  modified:
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - apps/api/services/tournament_outbox_service.py
    - apps/api/tests/repository/tournaments/test_outbox_poller.py
    - apps/bot/extensions/tournaments.py
decisions:
  - "Winners ping placed inside the CV2 LayoutView (a TextDisplay), not as a send content= kwarg, because discord.py's LayoutView send overloads accept no content; AllowedMentions still gates pings to numeric winner ids."
  - "_build_event repurposed to return (plural_routing_key, single_cycle_event); a separate _SINGLE_EVENT_STRUCT map converts each row, and _EVENT_ROUTING still raises KeyError on unknown types."
  - "_TransitionGroup dataclass accumulates per-cycle events + row ids per rotation group."
metrics:
  duration: ~20min
  completed: 2026-05-31
---

# Phase quick-260531-wbe Plan 01: Tournament CV2 Announcements + Single-Event Rotation Summary

Batched the per-category tournament cycle lifecycle events into ONE combined announcement each (grouped by `(event_type, created_at)` in the outbox poller, published on new plural routing keys) and replaced the dated Discord embeds on tournament alert/announcement surfaces with Components V2 LayoutView cards carrying a static hero image.

## What Was Built

### Task 1 — Batch SDK structs (`fa1ead2`)
Added `TournamentCyclesStartedEvent` (`cycles: list[TournamentCycleStartedEvent]`) and `TournamentCyclesCompletedEvent` (`cycles: list[TournamentCycleCompletedEvent]`) to `genjishimada_sdk.tournaments`, both registered alphabetically in `__all__`. The single-cycle structs are unchanged and become the per-entry element type.

### Task 2 — Grouped outbox publish (`6a944a4`)
`publish_pending_transitions` now iterates rows once, converts each payload into its single-cycle struct, runs the per-cycle `award_cycle_end` + `_reset_non_participant_streaks` side effects EXACTLY as before (once per row), and accumulates each event into a `_TransitionGroup` keyed by `(event_type, created_at)`. After grouping, it publishes ONE batch event per group on the plural routing key (`api.tournament.cycles_started` / `api.tournament.cycles_completed`) with idempotency key `tournament:{event_type}:{created_at_iso}`, then marks every row in the group published — all inside the same transaction (publish-before-mark preserved). Deferred XP events still publish after commit. `_EVENT_ROUTING` now maps to plural keys + batch structs; a new `_SINGLE_EVENT_STRUCT` map handles per-row conversion. `_build_event` returns `(plural_routing_key, per_cycle_event)` and still raises `KeyError` on unknown `event_type`.

The outbox test was updated to the grouped contract: `_seed_transition` accepts an optional `created_at`; `TestPublishAndMark` seeds two cycles sharing one rotation timestamp and asserts ONE publish per group with `data.cycles` length 2 and all rows marked published; `TestSkipLocked` reads the row's `created_at` to build the new plural idempotency key. `TestPublishFailure`, `TestCycleEndRewardHook`, `TestPoolNotReady`, `TestBuildEvent` kept semantically intact.

### Tasks 3 + 4 — CV2 batch consumers + command cards (`9800eab`)
- `_on_cycle_started` / `_on_cycle_completed` subscribe to the plural routing keys and decode the batch structs. Each renders ONE `ui.LayoutView` containing a single `ui.Container` (blurple started / gold completed) with a header, a static `_TOURNAMENT_GALLERY_IMAGE` hero `MediaGallery`, and a `Separator`-delimited `TextDisplay` section per category (map link + code, difficulty, ends-at for started; podium + crown for completed).
- Completed handler transfers EVERY category's champion role FIRST (caching the category object per entry, reused for rendering), then posts the single results card LAST. All non-None winners are aggregated into one ping built from numeric `<@id>` only, with an `AllowedMentions(users=[Object(id=w) for w in winners], everyone=False, roles=False)` allow-list.
- `/tournament info` (blurple), `/tournament streak` (green), `/tournament-reroll` (blurple) converted to `ui.LayoutView` via `edit_original_response(view=...)`. All data-fetch, the local `ends_at` computation, zero-state copy, and the reroll mod-gate are behavior-preserved. `map_banner` / `set_thumbnail` removed from all four tournament surfaces. Leaderboard + verification views left untouched (already CV2).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Winners ping moved inside the CV2 card instead of `send(content=...)`**
- **Found during:** Task 3 (`just lint-bot` basedpyright)
- **Issue:** The plan specified `await channel.send(content=content, view=view, allowed_mentions=...)` for the results card. discord.py's `Messageable.send` overloads that accept a `LayoutView` for `view=` accept NO `content=` kwarg (the `content`-accepting overloads only accept `view: View`, and `LayoutView` is not a `View` subclass), so pyright rejected the combination ("No overloads for send match").
- **Fix:** The winners ping is now appended as a `ui.TextDisplay` inside the results `Container` (`"Congratulations <@id> ...!"`). The mentions still fire only because every winner id is on the `AllowedMentions` allow-list; the ping text is built from numeric ids ONLY. The threat-model invariant (numeric `<@id>` mentions + winner-only allow-list, never free-text names) is fully preserved.
- **Files modified:** `apps/bot/extensions/tournaments.py`
- **Commit:** `9800eab`

**2. [Rule 3 - Blocking] SDK reinstall after struct change**
- **Found during:** Task 2 (running the outbox test)
- **Issue:** `ModuleNotFoundError: No module named 'genjishimada_sdk'` after editing the SDK (known workspace caveat noted in the plan + project memory).
- **Fix:** Ran `just fix` to reinstall the workspace SDK. Not a code change.

## Verification

All four plan verification commands pass:
- `just lint-sdk` — passed (Ruff + BasedPyright strict, 0 errors)
- `just lint-api` — passed (0 errors)
- `just lint-bot` — passed (0 errors)
- `uv run --directory apps/api pytest tests/repository/tournaments/test_outbox_poller.py -p no:xdist` — 7 passed

## Threat Model Invariants Preserved
- Per-cycle XP grant + streak advance + non-participant streak reset still run ONCE PER ROW (per cycle), independent of grouping (T-WBE-02) — `TestCycleEndRewardHook` still asserts per-cycle `award_cycle_end`.
- Numeric-only `<@id>` mentions; free-text `entry.name` / standings name never interpolated into a mention (T-10-10).
- `AllowedMentions(everyone=False, roles=False)` with only numeric winner ids allow-listed on every announcement/results post (T-11-19).
- No SQL migration, no `pending_transitions` schema change, no pg_cron change.

## Known Stubs
- `_TOURNAMENT_GALLERY_IMAGE = "https://cdn.genji.pk/assets/tournament-hero.png"` in `apps/bot/extensions/tournaments.py` is a placeholder hero URL carrying a `# TODO: swap for real tournament artwork` comment, exactly as the plan specified ("static placeholder hero image"). Intentional per plan; the asset URL can be repointed without code changes.

## Self-Check: PASSED

All four modified source files exist on disk and all three task commits (`fa1ead2`, `6a944a4`, `9800eab`) are present in git history.
