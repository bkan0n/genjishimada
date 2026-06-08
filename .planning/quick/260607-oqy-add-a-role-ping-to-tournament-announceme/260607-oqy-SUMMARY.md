---
phase: quick-260607-oqy
plan: 01
subsystem: bot
tags: [discord, tournaments, roles, allowed-mentions, config, msgspec, components-v2]

requires:
  - phase: 12.1
    provides: "_on_edition_rollover + _on_edition_results CV2 announcement send sites; ServerRoleSelectView role-react picker"
provides:
  - "tournament_announcements pingable role config field (struct + dev/prod TOML)"
  - "role ping on both public tournament announcement cards (rollover + deferred results)"
  - "self-assignable Tournament Announcements toggle in the #role-react view"
affects: [tournaments, bot-config, role-react]

tech-stack:
  added: []
  patterns:
    - "Sentinel-guarded role ping: 0 config value yields no ping line + roles=False (no broken <@&0>)"
    - "Centralized _tournament_ping helper returns (leading TextDisplay items, AllowedMentions roles value) for both CV2 send sites"
    - "Conditional ActionRow children built as a list then splatted into ui.ActionRow to drop unconfigured buttons"

key-files:
  created: []
  modified:
    - apps/bot/utilities/config.py
    - apps/bot/configs/dev.toml
    - apps/bot/configs/prod.toml
    - apps/bot/extensions/tournaments.py
    - apps/bot/extensions/information_pages.py

key-decisions:
  - "Single source of truth: role-react toggle + both announcement sends all read mentionable.tournament_announcements; no duplicate snowflake"
  - "Placeholder role id 0 in both TOMLs (real ID supplied at deploy); guards everywhere skip rendering/pinging while unconfigured"
  - "Refactored the role ping into a _tournament_ping helper to keep _on_edition_rollover under Ruff PLR0912/PLR0915 branch/statement limits"

patterns-established:
  - "Sentinel-guard pattern reused at all three touch points (two sends + role-react button)"

requirements-completed: [QUICK-260607-oqy]

duration: 12min
completed: 2026-06-07
---

# Quick Task 260607-oqy: Tournament Announcement Role Ping Summary

**Both public tournament announcement cards now ping a dedicated, self-assignable `tournament_announcements` role, gated behind a `0` config sentinel so an unconfigured role never renders a broken mention.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3 completed
- **Files modified:** 5

## Accomplishments

- **Task 1 — Config field:** Added `tournament_announcements: int` to the `Mentionable` msgspec struct (after `general_announcements`) and a matching `tournament_announcements = 0  # TODO: real tournament announcement role ID` key under `[roles.mentionable]` in both `dev.toml` and `prod.toml`. Both configs decode cleanly via `config.decode` (`forbid_unknown_fields=True` passes). Commit `1ea2964`.
- **Task 2 — Announcement pings:** Added a `_tournament_ping()` helper that returns the leading `ui.TextDisplay` role-mention item(s) and the `AllowedMentions.roles` value. Both `_on_edition_rollover` (combined rollover card) and `_on_edition_results` (deferred results card) prepend the `<@&role_id>` ping inside the CV2 container and pass `roles=[discord.Object(id=role_id)]`. When the role id is the `0` sentinel, the helper returns no ping line and `roles=False`. The mod-only `_on_completion_created` verification card is byte-for-byte unchanged. Commit `c9c39e4`.
- **Task 3 — Self-assignable toggle:** Refactored the "Announcement Pings" `ui.ActionRow` in `ServerRoleSelectView.rebuild_components` to build its buttons as a list, conditionally appending a "Tournament Announcements" `ServerRoleToggleButton` (emoji 🏆) sourced from `mentionable.tournament_announcements`, then splatting into `ui.ActionRow(*announcement_buttons)`. The button is skipped while the role id is `0`, avoiding the `_set_guild_and_role` assert on `get_role(0)`. Commit `6455051`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Ruff PLR0912/PLR0915 in `_on_edition_rollover`**
- **Found during:** Task 2 (`just lint-bot`)
- **Issue:** Adding the inline role-ping branch + statements pushed `_on_edition_rollover` over Ruff's "too many branches" (13 > 12) and "too many statements" (54 > 50) thresholds, failing lint.
- **Fix:** Extracted the role-ping logic into a `_tournament_ping()` helper method shared by both send sites. This both removed the added branch/statements from the handler and centralized the role-ping construction (single source of truth), instead of just suppressing the rule.
- **Files modified:** apps/bot/extensions/tournaments.py
- **Commit:** c9c39e4

Note: Ruff's formatter also reformatted `tournaments.py` (line-wrapping) as part of `just lint-bot`; this is expected formatter behavior, not a content change.

## Verification

- `config.decode` succeeds for both `dev.toml` and `prod.toml` with the new field (Task 1 automated check passed: "OK both configs decode with tournament_announcements").
- `just lint-bot` passes — Ruff format (44 files unchanged), Ruff check (All checks passed), BasedPyright (0 errors, 0 warnings, 0 notes).
- Task 2 grep: `>= 2` non-comment `tournament_announcements` references in `tournaments.py` — passed.
- Task 3 grep: `information_pages.py` references `mentionable.tournament_announcements` — passed.
- `git diff` confirms no changes near `_on_completion_created` (mod verification card unchanged).

## Known Stubs

The `tournament_announcements` role id is the `0` sentinel in both `dev.toml` and `prod.toml`, marked with `# TODO: real tournament announcement role ID`. This is intentional per the plan (the maintainer supplies the real Discord role IDs at deploy). All three touch points (both sends + the role-react toggle) explicitly guard against the `0` sentinel: the ping line and allow-list are skipped on the sends, and the self-assign button is not registered. The feature is dormant-but-safe until the real IDs are set.

## Self-Check: PASSED
