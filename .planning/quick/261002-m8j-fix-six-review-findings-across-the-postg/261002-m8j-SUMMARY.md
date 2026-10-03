---
phase: quick-261002-m8j
status: complete
completed: 2026-10-02
requirements_completed: [REVIEW-72-DEPENDENCY, REVIEW-72-LIVENESS, REVIEW-73-POOL, REVIEW-73-ORDERING, REVIEW-74-ALERT, REVIEW-75-IMPORT]
---

# Queue stack review repairs

All six findings in PRs #72–#75 are repaired, with regressions that reproduced the original failures before implementation. Each fix was committed to its originating PR branch; lower branches were merged forward without rewriting published history.

| PR | Repair | Commits |
| --- | --- | --- |
| #72 | Reconcile held dependency failures before dequeue, covering both terminal-write orders and concurrent commits. Restrict the function to queue workers and keep discarded/uncertain work held. | `d064345` |
| #72 | Bound shared database operations, including waits for the driver lock. Terminate stalled connections so supervision cancels stale execution and reconnects. | `05dfff4` |
| #73 | Preserve the underlying pool identity outside ambient transactions; retain transaction-aware acquisition and rollback. | `7da8cf3` |
| #73 | Give both tournament manual-review producers their own completion namespace while preserving tournament OCR ordering. | `13aef9a` |
| #74 | Refresh recovered alert content and controls before acknowledgement; failed edits remain retryable without duplicate cards or notifications. | `57df55a` |
| #75 | Hold claimed, partially executed, or ambiguous legacy imports. Prefer stored execution evidence and propagate conflicting evidence across duplicate identities before any enqueue. | `77ac5c5`, `3a6606a` |

## Verification

- Full queue acceptance: **132 passed**, including real process-death and database-restart cases; no skips or expected failures.
- Full API suite: **1,988 passed, 2 skipped, 2 expected failures**. The skipped/expected-failure counts match the baseline.
- Ruff formatting and lint passed across API, bot, SDK, and queue scripts.
- API, bot, SDK, and queue script type checks: **zero errors and warnings**. API analysis explicitly used the workspace virtual environment.
- Importer repair independently reviewed; **33 focused importer/operations tests passed**, including duplicate source ordering, transitive identities, stored execution history, and concurrent imports.
- Independent review of the dependency and database-liveness repairs found no remaining issues.
- Targeted red-to-green evidence: eight pool cases, two namespace cases, seven alert cases, two dependency ordering cases, two database contention cases, nine initial importer cases, and five duplicate/history cases failed before their corresponding repairs.
- Original commits remain ancestors of all four updated branches, and each lower PR head is an ancestor of the next branch.

## Decisions and deviations

The importer fails closed for work that may have executed. It does not fabricate completed-effect receipts or external message bindings. The runbook explains the required never-started evidence and why apply may hold more work than an offline dry-run.

Independent review found that a second, apparently unstarted copy could bypass a held partial copy. The importer now groups public UUIDs and event identities, includes previously recorded dispositions, and serializes competing imports before checking evidence. This extends the original importer repair to close that concrete replay path.

The queue schema change remains in the undeployed migration 0034. Queue-only credentials retain their domain-table restrictions. Alert regressions run in the existing queue acceptance job with fake transports; no Discord login is required.

The three implementation groups used explicitly owned worktrees. GSD's plan was committed separately, and worker commits were cherry-picked to their original PR branches before forward merges. No production services, databases, broker resources, or credentials were changed.
