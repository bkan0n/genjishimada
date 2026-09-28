---
status: complete
task: 260928-m9b
date: 2026-09-28
---

# API test reorganization

Reorganized the existing API suite around feature folders and explicit resource
ownership, using doompk's testing approach while retaining Genji's asyncpg stack.
No test cases were added. Normal application defaults are unchanged.

## Changes

- One migrated database per worker; restore actual seed rows and sequence state
  before each database test, including mutable configuration and reference data.
- Centralized connections, bounded pools, factories, service mocks, and HTTP
  clients. Removed fixture shadowing, per-factory pools, incidental event sleeps,
  and cleanup that compensated for data left by previous tests.
- Test apps disable scheduled pollers explicitly. The test client completes real
  business listeners before returning, while external email/OCR events are recorded.
- Test apps skip repeated Sentry initialization and use synchronous logging.
  Existing application defaults still initialize Sentry and queue-backed logging.
- Moved 116 API test modules into feature folders and classified actual fixture
  requirements with unit/database/integration markers. The 46 bot cases are unchanged.
- Strengthened existing infrastructure and empty-result assertions. Added a
  migration manifest/verifier preserving all case IDs, parameters, and skip/xfail
  expressions: 1,937 API cases plus 46 bot cases, 1,983 total.
- Standardized complete-suite execution with two workers, reverse/seeded shuffle
  options, strict configuration, useful durations, and bounded CI. Testmon is opt-in.
- CI supports all PR base branches so the complete stack can be validated together.

## Commits and stack

1. `e39cfc0` through `537a572` — `tests/api-foundation`, targeting `main`: [PR #68](https://github.com/bkan0n/genjishimada/pull/68).
2. `6b21c6f` and `98b5ec6` — `tests/api-feature-layout`, targeting `tests/api-foundation`: [PR #69](https://github.com/bkan0n/genjishimada/pull/69).
3. `040cd60` and `4943b05` — `tests/api-runner`, targeting `tests/api-feature-layout`.

The runner PR is published after this tracking commit. All PRs remain drafts and
unmerged pending joint review.

## Verification

- Exact original case/parameter/skip inventory preserved across all 120 test files.
- Independent foundation and final integration reviews found no actionable issues.
- API lint, new runner/inventory lint, and focused app/runner/inventory type checks pass.
- Foundation targeted run: 359 passed in 32.23 seconds with two workers.
- Initial complete parallel run: 1,979 passed, 2 skipped, 2 xfailed in 162.06 seconds.
- Existing resource-ownership and notification cases: 91 passed in 26.75 seconds.
- Unit-only run with an unavailable Docker socket: 430 passed in 6.25 seconds.
- Final serial: 1,979 passed, 2 skipped, 2 xfailed; pytest reported 272.03 seconds.
- Reverse serial: 1,979 passed, 2 skipped, 2 xfailed; pytest reported 275.54 seconds.
- Final shuffled two-worker run (seed 20260928): 1,979 passed, 2 skipped, 2 xfailed
  in 149.92 seconds reported by pytest; **151.31 seconds total wall time**, including
  process exit.

Timings are local measurements; they are not direct comparisons with GitHub runner
performance. Historical stalls were not investigated further, as requested.
The serial pytest durations exclude some final garbage collection/process exit;
the final parallel measurement records total wall time.

## Decisions

- Restore mutable seed data instead of excluding configuration tables from resets.
- Keep function-scoped async resources to avoid cross-loop ownership.
- Preserve every existing test case; adapt the three existing infrastructure cases
  to exercise baseline restoration and default application controls.
- Retain two workers as the predictable default and allow an explicit override.
- No new tests, dependency updates, application behavior changes, or bot rewrites.

## Validation finding resolved

The first final serial run accumulated more than 1,800 logging/Sentry threads and
roughly 5 GB of memory while repeatedly constructing apps. It was stopped after
capturing diagnostics. A small construction probe reproduced logging-thread
growth (2 to 7 threads after five apps). Explicit test-only logging and Sentry
controls keep the same probe at 2 threads. The existing infrastructure case now
checks this property, and an independent follow-up review confirmed unchanged
production defaults.
