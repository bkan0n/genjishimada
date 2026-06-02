---
status: testing
phase: 03-repository-layer
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md]
started: 2026-05-30T21:55:01Z
updated: 2026-05-30T21:55:01Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

number: 1
name: Tournament Repository Test Suite
expected: |
  Running `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist`
  executes all 39 tournament repository integration tests and every one passes
  (config, categories, cycles, completions, streaks, map selection, pending transitions).
awaiting: user response

## Tests

### 1. Tournament Repository Test Suite
expected: All 39 tournament repository integration tests pass (config, categories, cycles, completions, streaks, map selection, pending transitions).
result: [pending]

### 2. Cross-Write CTE Behavior
expected: cross_write_to_core inserts into core.completions ONLY when the tournament time beats the user's existing best; it is a no-op when the time is slower or equal. The "latest = fastest" invariant in core.completions is preserved.
result: [pending]

### 3. Leaderboard Ranking
expected: fetch_leaderboard returns one row per user (their best submission), ranked verified-first then by ascending time, with RANK() positions and a resolved display name.
result: [pending]

### 4. Lint & Type-Check Clean
expected: `just lint-api` (ruff format + ruff check + basedpyright) reports 0 errors across the new tournament repository and test files.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

[none yet]
