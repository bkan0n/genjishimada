---
phase: 5
slug: map-selection-blacklist
status: final
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-29
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio, pytest-mock, pytest-databases[postgres] |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~30 seconds (targeted), ~120 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `ruff check` + `basedpyright`
- **After every plan wave:** Run `just test-api`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 05-01-01 | 01 | 1 | CYCLE-04, CYCLE-05 | lint | `uv run --directory apps/api ruff check --select E,F,I,ANN` | pending |
| 05-01-02 | 01 | 1 | CYCLE-04, CYCLE-05, CYCLE-07 | lint | `uv run --directory apps/api ruff check --select E,F,I,ANN` | pending |
| 05-02-01 | 02 | 2 | CYCLE-05, CYCLE-06, CYCLE-07 | lint+import | `uv run --directory apps/api ruff check --select E,F,I,ANN` | pending |
| 05-02-02 | 02 | 2 | CYCLE-05, CYCLE-06, CYCLE-07 | lint+import | `uv run --directory apps/api ruff check --select E,F,I,ANN` | pending |
| 05-03-01 | 03 | 3 | CYCLE-05, CYCLE-06, CYCLE-07 | unit | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` | pending |
| 05-03-02 | 03 | 3 | CYCLE-04, CYCLE-05, CYCLE-06, CYCLE-07 | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py -v -p no:xdist` | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

- Existing test infrastructure covers all phase requirements (pytest + pytest-databases already configured)
- Test files created in Plan 03 (Wave 3): `tests/services/test_tournament_service.py`, `tests/integration/test_tournaments_integration.py` (extended)

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: waves 1-2 use lint verification, wave 3 adds functional tests
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-29
