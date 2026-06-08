---
phase: 6
slug: submission-flow-leaderboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-29
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5+ with pytest-asyncio (mode: auto) |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournaments_integration.py -v -p no:xdist` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournaments_integration.py -v -p no:xdist`
- **After every plan wave:** Run `just test-api`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | SUB-01 | — | N/A | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestSubmitCompletion -v -p no:xdist` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SUB-02 | — | N/A | unit | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestSubmitCompletion::test_rejects_slower_time -v -p no:xdist` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SUB-03 | — | N/A | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestSubmitCompletion::test_cross_write -v -p no:xdist` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SUB-04 | — | N/A | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestSubmitCompletion::test_cross_write_sets_fk -v -p no:xdist` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SUB-05 | — | N/A | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestLeaderboard -v -p no:xdist` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SUB-06 | — | N/A | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestCycleListing -v -p no:xdist` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/services/test_tournament_service.py::TestSubmitCompletion` — stubs for SUB-01, SUB-02
- [ ] `tests/services/test_tournament_service.py::TestGetLeaderboard` — stubs for SUB-05
- [ ] `tests/services/test_tournament_service.py::TestListCycles` — stubs for SUB-06
- [ ] `tests/integration/test_tournaments_integration.py::TestSubmitCompletion` — stubs for SUB-03, SUB-04
- [ ] `tests/integration/test_tournaments_integration.py::TestLeaderboard` — stubs for SUB-05
- [ ] `tests/integration/test_tournaments_integration.py::TestCycleListing` — stubs for SUB-06

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
