---
status: partial
phase: 12-overhaul-of-tournaments
source: [12-VERIFICATION.md]
started: 2026-06-01
updated: 2026-06-01
---

## Current Test

[awaiting human testing]

## Tests

### 1. End-to-end rollover card in Discord
expected: Triggering a full rollover on the dev server renders ONE combined CV2 card with both a results section (previous edition winners) and a starting section (new edition maps); winner pings render via `ui.TextDisplay` with the AllowedMentions allow-list (numeric `<@id>` only, no @everyone/@here).
result: [pending]

### 2. Into-hiatus rollover (results-only) visual check
expected: With transitions paused before a boundary, the rollover card renders results-only — no "starting" section — and no next edition is created (D-12 hiatus). On resume, the next edition snaps to the next grid boundary and renders a starting-only card (D-13a).
result: [pending]

### 3. pg_cron job registration on VPS
expected: Querying `cron.job` on the dev/prod database shows the tournament transition job points at `tournaments.process_edition_transitions()` (the cron (un)schedule block no-ops in the test DB, so this can only be confirmed against a real pg_cron-enabled instance).
result: [pending]

### 4. Fresh-restart wipe verification on VPS
expected: After the 0024 migration runs against a populated database, `tournaments.cycles` / `tournaments.completions` / `tournaments.editions` reflect a clean fresh start, while `core.completions` PB rows are intact (row count unchanged) with `tournament_completion_id` NULLed on previously cross-written rows (D-15 — no cascade-delete of PBs).
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
