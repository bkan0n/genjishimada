---
status: partial
phase: 10-bot-slash-commands
source: [10-VERIFICATION.md]
started: 2026-05-30T20:23:08Z
updated: 2026-05-30T20:23:08Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. `/tournament info` rich card visual rendering
expected: On a category with an active cycle, the command shows an ephemeral rich card matching the Phase-9 new-cycle embed — map name, clickable workshop-code link, difficulty, category name, map thumbnail, and time remaining as relative (`in 3 days`) + absolute Discord timestamps.
result: [pending]

### 2. `/tournament leaderboard` visual pagination
expected: On a cycle with >10 submissions, the command shows a paginated leaderboard (10 per page) using the project's custom paginator with working page buttons; rows render as `<@user>` mentions. Empty cycle shows "No submissions yet — be the first!".
result: [pending]

### 3. `/tournament streak` zero-state and with-record rendering
expected: As the invoking user (self-only), shows current + max streak ephemerally. With no streak record, shows current 0 / max 0 plus the encouraging line "Submit in a cycle to start your streak!" (not an error).
result: [pending]

### 4. `/tournament-reroll` non-admin rejection (live guild)
expected: Invoked by a non-Mod/non-Sensei user in the dev guild, the command is rejected ephemerally via UserFacingError and NO reroll/API write occurs.
result: [pending]

### 5. `/tournament-reroll` admin success (random + explicit code)
expected: Invoked by a Mod or Sensei, a bare invocation rerolls the category's next-cycle map randomly and the reply shows the newly-selected map; supplying an Overwatch `code` chooses that specific map (choose-map path).
result: [pending]

### 6. `CategoryTransformer` live autocomplete
expected: Typing a partial category name in the `category` arg of `/tournament info` / `leaderboard` / `-reroll` shows live autocomplete suggestions from the API's admin-created categories (≤25 results).
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
