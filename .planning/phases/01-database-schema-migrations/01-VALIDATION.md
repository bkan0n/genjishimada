---
phase: 01
slug: database-schema-migrations
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-29
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio, pytest-databases[postgres] |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run --directory apps/api pytest tests/ -v -p no:xdist -x` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run --directory apps/api pytest tests/ -v -p no:xdist -x`
- **After every plan wave:** Run `just test-api`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | foundation | — | N/A | integration | `uv run --directory apps/api pytest tests/test_tournament_schema.py -v -p no:xdist` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_tournament_schema.py` — migration runs cleanly, tables exist, constraints verified
- [ ] Existing `conftest.py` fixtures cover database provisioning

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Migration runs against production-like data | foundation | Requires VPS import | Run `./scripts/import-db-from-vps.sh dev` then apply migration |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
