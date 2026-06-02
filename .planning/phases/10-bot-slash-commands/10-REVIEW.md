---
phase: 10-bot-slash-commands
reviewed: 2026-05-30T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - apps/api/routes/v3/tournaments.py
  - apps/api/services/exceptions/tournaments.py
  - apps/api/services/tournament_service.py
  - apps/api/tests/bot/test_tournament_commands.py
  - apps/api/tests/bot/test_tournaments_handler.py
  - apps/api/tests/integration/test_tournaments_integration.py
  - apps/api/tests/services/test_tournament_service.py
  - apps/bot/extensions/api_service.py
  - apps/bot/extensions/tournaments.py
  - apps/bot/utilities/transformers.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-05-30T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the new Discord tournament slash commands (`/tournament info|leaderboard|streak`, `/tournament-reroll`), the bot `APIService` tournament wrappers, the `CategoryTransformer`, and the new API `GET /tournaments/streaks/{user_id}` endpoint plus its service/exception wiring.

The five high-risk areas called out in the brief are all correctly handled:

- **Reroll admin gate (authoritative access control):** `TournamentRerollCog.tournament_reroll` raises `UserFacingError` *before* any API call when the invoker holds neither the Mod nor Sensei role (`apps/bot/extensions/tournaments.py:444-452`). The raise happens after `defer()` but before either `reroll_next_cycle`/`choose_next_cycle`, so a non-admin can never trigger an API write. `on_command_error` (`apps/bot/utilities/errors.py:191-207`) renders this as an ephemeral message. The `reroll_gate` unit test asserts no API write. Sound.
- **Streak 404→zero mapping:** `streak` catches `APIHTTPError`, re-raises when `e.status != HTTPStatus.NOT_FOUND` (`tournaments.py:398-402`). `HTTPStatus.NOT_FOUND` is an `IntEnum`, so the `int` status from aiohttp compares correctly. Non-404 is *not* swallowed (covered by `test_streak_zero_does_not_swallow_non_404`). Sound.
- **Leaderboard empty short-circuit:** `leaderboard` returns the friendly message before constructing `TournamentLeaderboardPaginator` when `entries` is empty (`tournaments.py:369-371`), avoiding the `% len(self._pages)` modulo-by-zero in `StaticPaginatorView._get_requested_index` / `navigate_to_page`. Sound.
- **Mention-injection:** Both the results podium (`tournaments.py:145`) and leaderboard rows (`tournaments.py:270`) render numeric `<@{entry.user_id}>` only; the free-text `entry.name` is never interpolated. `AllowedMentions(everyone=False, roles=False)` on the results send (`:163`) further hardens the announcement. Sound.
- **New endpoint scope + service/route pattern:** `GET /tournaments/streaks/{user_id}` declares `tournaments:read` (`apps/api/routes/v3/tournaments.py:196`); service raises `StreakNotFoundError`, route converts to 404 (`:215-221`). Integration tests cover 200/404/401. Sound.

No blockers found. Remaining items are robustness/quality concerns.

## Warnings

### WR-01: Leaderboard view is sent but never bound for interaction-component auth before the await returns

**File:** `apps/bot/extensions/tournaments.py:373-375`
**Issue:** The paginator is created and sent, then `view.original_interaction = itx` is assigned *after* `await itx.edit_original_response(view=view)`. `original_interaction` is consumed by `BasePaginatorView`/`BaseView` error handling and (in the wider codebase) for ownership/timeout edits. Because it is set only after the message is already live, there is a window where a button callback firing between the send completing and the attribute assignment would see `original_interaction is None`. Practically the window is sub-millisecond and Discord cannot deliver a component interaction that fast, but the ordering is inverted relative to the `info`/other command conventions and is fragile.
**Fix:** Assign before sending:
```python
view = TournamentLeaderboardPaginator(f"{category_data.name} — Leaderboard", entries)
view.original_interaction = itx
await itx.edit_original_response(view=view)
```

### WR-02: `info` silently omits the "Ends" field when `started_at` is None on an active cycle

**File:** `apps/bot/extensions/tournaments.py:328-334`
**Issue:** The card only renders the "Ends" field when `active.started_at is not None`. For a cycle whose status is genuinely `active` (the only kind reaching this branch — see `list_tournament_cycles(status="active")`), `started_at` should always be set; if it is ever `None`, the user gets a card with no end time and no explanation. This is a latent contract assumption: an active cycle without `started_at` indicates upstream data corruption that is then silently hidden from the operator rather than surfaced. The `info` command has no test for the `started_at is None` path.
**Fix:** Either assert/log when an active cycle lacks `started_at`, or render an explicit "Ends: unknown" so the anomaly is visible:
```python
if active.started_at is not None:
    ...
else:
    log.warning("[!] [Tournament] active cycle %s has no started_at; omitting end time", active.id)
```

### WR-03: `_request` debug-logs query params with f-string interpolation, violating the project %s-logging convention

**File:** `apps/bot/extensions/api_service.py:369`
**Issue:** `log.debug(f"The params inside of _request show as {params}")` uses an f-string. CLAUDE.md mandates `%s`-style logging (lazy formatting) project-wide. Beyond the convention, this string-builds on every request even when DEBUG is disabled, and `params` here can include user-supplied search/category values — eager interpolation into a log line is the kind of pattern that leaks input into logs. The same f-string anti-pattern appears at `:490-491` (`get_maps`). These predate this phase but sit in a reviewed file and were not corrected.
**Fix:**
```python
log.debug("The params inside of _request show as %s", params)
```

## Info

### IN-01: `CategoryTransformer.transform` accepts a raw digit string as a category ID without verifying it exists

**File:** `apps/bot/utilities/transformers.py:269-270`
**Issue:** When the user types a numeric value, the transformer returns `int(value)` immediately without confirming the category exists. A bogus numeric input flows to the API, which returns 404 (mapped to an "unknown error" view rather than the friendly `Unknown category:` message used for the name path at `:275`). Inconsistent UX between the two input paths.
**Fix:** Optionally validate the numeric path against the live category list, or document that numeric IDs are trusted passthrough.

### IN-02: `CodeAllTransformer.transform` return annotation is `str` but the reroll parameter is typed `OverwatchCode`

**File:** `apps/bot/utilities/transformers.py:182` (and `apps/bot/extensions/tournaments.py:429`)
**Issue:** `transform` returns `value` annotated `str`, while the command parameter is `app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer]`. `OverwatchCode` is an `Annotated[str, Meta(...)]`, so this is benign at runtime, but the transformer does not actually enforce the `OverwatchCode` `Meta` constraints (length/charset) — it only checks `CODE_VERIFICATION` regex and existence. The type signature overstates the guarantee.
**Fix:** Align the annotation, or rely on the regex check being equivalent to the `OverwatchCode` constraint (and note it).

### IN-03: Magic cadence constants (7 / 14 days) inlined in the info command

**File:** `apps/bot/extensions/tournaments.py:329`
**Issue:** `dt.timedelta(days=7 if category_data.cycle_frequency == "weekly" else 14)` hardcodes the weekly/biweekly day counts inline. The same cadence math likely exists API-side (where cycles are actually scheduled). Drift risk: if the API ever changes biweekly to a different interval, this client computation silently diverges.
**Fix:** Extract `_WEEKLY_DAYS = 7` / `_BIWEEKLY_DAYS = 14` module constants, or have the API return `ends_at` (the comment at `:328` notes this was deliberately computed client-side to avoid an API change — acceptable, but the magic numbers should still be named).

### IN-04: `PageNumberModal.on_submit` re-raises `ValueError` as `TypeError`, mislabeling the error

**File:** `apps/bot/utilities/paginator.py:117-121`
**Issue:** Non-numeric or out-of-range page input is caught as `ValueError` and re-raised as `TypeError("Invalid integer.")`. The exception type is semantically wrong (it is a value error, not a type error) and loses the original "Value out of range." distinction. Pre-existing, reachable from the new leaderboard paginator's page-jump button.
**Fix:** Raise `UserFacingError("Page must be an integer in range 1 - N.")` so it renders as a friendly message instead of an "unknown error" view.

---

_Reviewed: 2026-05-30T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
