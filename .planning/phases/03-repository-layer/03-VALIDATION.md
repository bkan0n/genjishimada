---
phase: 03
slug: repository-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-29
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio, pytest-databases[postgres] |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~15 seconds (repository tests only) |

---

## Sampling Rate

- **After every task commit:** Run `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist`
- **After every plan wave:** Run `just test-api`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 03-01-01 | 01 | 0 | foundation | fixture | `uv run --directory apps/api pytest tests/repository/tournaments/conftest.py --collect-only` | pending |
| 03-01-02 | 01 | 1 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_config.py -v -p no:xdist` | pending |
| 03-01-03 | 01 | 1 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_categories.py -v -p no:xdist` | pending |
| 03-01-04 | 01 | 1 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_cycles.py -v -p no:xdist` | pending |
| 03-02-01 | 02 | 2 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_completions.py -v -p no:xdist` | pending |
| 03-02-02 | 02 | 2 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_leaderboard.py -v -p no:xdist` | pending |
| 03-02-03 | 02 | 2 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_cross_write.py -v -p no:xdist` | pending |
| 03-02-04 | 02 | 2 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_streaks.py -v -p no:xdist` | pending |
| 03-02-05 | 02 | 2 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_transitions.py -v -p no:xdist` | pending |
| 03-02-06 | 02 | 2 | foundation | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_map_selection.py -v -p no:xdist` | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

- [ ] `tests/repository/tournaments/conftest.py` — shared fixtures (create_test_category, create_test_cycle, etc.)
- [ ] `tests/repository/tournaments/__init__.py` — package init
- [ ] Tournament schema migration applied to test database

*Existing pytest-databases[postgres] infrastructure handles DB lifecycle.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
