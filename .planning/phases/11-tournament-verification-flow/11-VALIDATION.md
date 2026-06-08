---
phase: 11
phase_slug: tournament-verification-flow
status: planning
created: 2026-05-31
validation_dimensions: 8
---

# Phase 11: Validation Strategy

**Purpose:** Define how each success criterion will be validated (Nyquist Dimension 8 — Verification Coverage).

This document maps every phase success criterion to a concrete validation method BEFORE planning. The planner reads this to ensure every plan includes verification tasks. Source: `11-RESEARCH.md` §Validation Architecture.

## Validation Dimensions

1. **Existence** — Does the artifact exist?
2. **Executes** — Does it run without crashing?
3. **Behavior** — Does it produce correct output for valid input?
4. **Negative** — Does it handle invalid input gracefully?
5. **Integration** — Does it work with other components?
6. **Idempotency** — Can it run repeatedly without side effects?
7. **State** — Does it leave the system in a valid state?
8. **Observability** — Can you verify it worked?

Tournament verification is integration-heavy (completion flow ↔ tournament domain ↔ RabbitMQ ↔ bot), so validation leans on integration tests against the real test DB plus the `X-PYTEST-ENABLED` publish-skip seam.

## Success Criteria → Validation Mapping

| Criterion | Validation Method | Dimension(s) | Automated? |
|-----------|-------------------|--------------|------------|
| SC-1: Verified completion on cycle map → leaderboard | Integration test: submit normal completion on active-cycle map via API, verify it, assert it appears on `GET /tournaments/cycles/{id}/leaderboard` | Behavior, Integration, Observability | yes |
| SC-2: Slower-than-PB run still verified + recorded (fastest tournament time kept) | Integration test: seed faster core PB, submit slower run on cycle map, assert tournament row created + verifiable + on leaderboard; submit a second slower run, assert fastest-kept | Behavior, Negative, State | yes |
| SC-3: PB-and-tournament run verified once, marks both | Integration test: submit new-PB run on cycle map, verify once, assert BOTH `core.completions.verified` AND tournament row verified via a single verification artifact | Behavior, Integration, Idempotency | yes |
| SC-4: Bypass endpoint gone, no unverified tournament writes | Source assertion (grep route absent) + integration test: old endpoint 404s; no code path writes a tournament completion as verified without verification | Existence, Negative | yes |
| SC-5: XP + standing only on verification | Integration test: submit (no verify) → assert no participation XP row + unverified rank; verify → assert XP row + verified rank | Behavior, State, Idempotency | yes |
| SC-6: core.completions latest=fastest preserved | Integration test: slower tournament run does NOT insert into `core.completions` (row count unchanged); 0017 trigger still blocks slower core inserts | Negative, State | yes |
| SC-7 (cross-cutting): per-cycle speed enforcement + idempotent XP | Integration test: duplicate verify → one XP grant (ledger UNIQUE); reset sweep re-runs cleanly | Idempotency, State | yes |

## Validation Requirements by Plan

_Populated after planning — each plan maps to the SC validation tasks above._

| Plan | Validation Tasks | Coverage |
|------|------------------|----------|
| _TBD_ | _TBD_ | _TBD_ |

## Notes

- Regression guard (D7): because the shared `submit_completion` hot path is modified, normal
  (non-tournament) submission behavior — including the existing `SlowerThanPendingError` HTTP 400 on
  non-tournament maps — must be re-asserted by tests so the tournament relaxation does not leak.
- The exact exception raised by the `core.enforce_speed_rules_nonlegacy_only()` (0017) trigger must be
  confirmed at edit time so the non-PB path catches precisely it (see RESEARCH Open Questions / P7).
- Bot verify-accept path is tested via the bot test loader under `apps/api/tests/bot/`; API publish is
  skipped via `X-PYTEST-ENABLED=1`.
