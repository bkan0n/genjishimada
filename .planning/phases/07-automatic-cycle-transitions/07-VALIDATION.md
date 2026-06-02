---
phase: 7
slug: automatic-cycle-transitions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-30
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (auto) + pytest-databases[postgres] |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~60–120 seconds (full suite, 8 workers) |

---

## Sampling Rate

- **After every task commit:** Run the quick command scoped to the touched test module
- **After every plan wave:** Run `just test-api`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

> Populated by the planner / Nyquist auditor once PLAN.md tasks exist. Critical behaviors to cover (from RESEARCH.md § Validation Architecture):

| Critical Behavior | Requirement | Test Type | Notes |
|-------------------|-------------|-----------|-------|
| Transition atomicity (active→finalizing→completed + next active in one txn) | CYCLE-01 | integration | Invoke `SELECT tournaments.process_cycle_transitions()` directly; assert all-or-nothing on injected failure |
| End-time detection accuracy (weekly/biweekly interval math) | CYCLE-01 | integration | Seed cycles with `started_at` past/within window; assert only due cycles transition |
| Advisory-lock concurrency safety (no double transition) | CYCLE-01 | integration | Concurrent invocation; assert second call no-ops |
| Submission rejection during `finalizing` | CYCLE-01 | unit/integration | Assert `submit_completion` raises `CycleNotActiveError` when status != active (already enforced — regression guard) |
| Placement snapshot embedded in outbox payload | CYCLE-01 | integration | Assert `cycle_completed` payload standings match `fetch_leaderboard` ranking |
| Outbox at-least-once delivery (FOR UPDATE SKIP LOCKED, publish→mark) | CYCLE-01 | integration | Poller picks unpublished rows once; marks published; X-PYTEST-ENABLED skips real publish |
| SQL/Python map-selection parity (D-06 helper vs `fetch_eligible_maps`) | CYCLE-01 | integration | Parity test: SQL `select_eligible_map` respects blacklist window + difficulties + LRU fallback |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `apps/api/tests/tournaments/` — existing tournament test fixtures cover DB setup (reuse from phases 4–6)
- [ ] Transition function must be directly invocable in tests (`SELECT tournaments.process_cycle_transitions()`) since pg_cron is absent in the test DB

*Existing pytest + pytest-databases infrastructure covers all phase requirements — no new framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| pg_cron job actually fires on schedule | CYCLE-01 | pg_cron not loaded in test DB; cron timing not unit-testable | Verify on dev VPS: `SELECT * FROM cron.job WHERE jobname LIKE 'tournament%'`; observe transition after a real cycle end |
| Lifespan poller cancels cleanly on API shutdown | CYCLE-01 | Lifespan teardown is process-level | Start/stop API locally; confirm no orphaned task / clean shutdown logs |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
