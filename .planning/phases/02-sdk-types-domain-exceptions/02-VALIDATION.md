---
phase: 2
slug: sdk-types-domain-exceptions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-29
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `just lint-sdk` |
| **Full suite command** | `just lint-all` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `just lint-sdk`
- **After every plan wave:** Run `just lint-all`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | foundation | — | N/A | lint | `just lint-sdk` | — | ⬜ pending |
| 02-01-02 | 01 | 1 | foundation | — | N/A | lint | `just lint-all` | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No new test framework or fixtures needed — this phase defines types and exceptions only, validated by lint and type-check.

---

## Manual-Only Verifications

All phase behaviors have automated verification (lint + type-check).

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
