---
phase: 14
slug: skill-score-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-16
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `14-RESEARCH.md` → Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5+ with pytest-asyncio (auto mode), pytest-xdist (8 workers), pytest-databases[postgres] |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run pytest apps/api/tests/services/test_skill_service.py apps/api/tests/integration/test_skill_dashboard.py -x` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~quick: seconds; full suite: parallel (8 workers) |

Migrations apply automatically: `conftest.py:_apply_sql_dir` applies every `migrations/*.sql` in sorted order at session start, so the new `0031` migration auto-applies on the fresh test DB.

**Recompute is in-process, NOT RabbitMQ-gated** by `X-PYTEST-ENABLED=1`. Tests drive it via the `_recompute(pool)` helper (`test_skill.py:56-73`) which settles the fire-and-forget listener then runs `SkillService(...).recompute_all()` as the authoritative last writer.

---

## Sampling Rate

- **After every task commit:** `uv run pytest apps/api/tests/services/test_skill_service.py apps/api/tests/integration/test_skill_dashboard.py -x`
- **After every plan wave:** `just test-api` (full parallel suite)
- **Before `/gsd:verify-work`:** Full suite green + `just lint-api` + `just lint-sdk` clean
- **Max feedback latency:** quick run is seconds

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. Each task's `<acceptance_criteria>` maps to a requirement below; the executor records green/red here during execution.

| Req | Behavior to validate | Test Type | Automated Command | File Exists | Status |
|-----|----------------------|-----------|-------------------|-------------|--------|
| Req 1 | ≥2 history rows w/ distinct `captured_at` after 2 recomputes; no pre-rollout rows | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ W0 | ⬜ pending |
| Req 2 | verify → `PLAYER_ACTION` delta row for actor; bystanders → `MAP_ENVIRONMENT`; config/nightly/coalesced → `SYSTEM` "global recalculation" | integration + service | quick run | ❌ W0 (extend `test_skill_service.py`) | ⬜ pending |
| Req 3 | known 30d fixture → correct best/lowest/average + point/percent change; invalid window → 4xx; empty user → 200 empty + zero summary | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ W0 | ⬜ pending |
| Req 4 | feed desc by `captured_at`; `limit` bounds page; window respected; empty user → empty feed | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ W0 | ⬜ pending |
| Req 5 | `sum(main_causes.impact) + other_factors == delta` within 1e-6; foreign/unknown `change_id` → 404 | integration + service | quick run | ❌ W0 | ⬜ pending |
| Req 6 | each of 5 windows returns in-range only; `all` returns full; unknown window → 4xx | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ W0 | ⬜ pending |
| Req 7 | empty user: 200 empty/zero (history), empty feed, 404 (change_id); never 500 | integration | `pytest tests/integration/test_skill_dashboard.py -x` | ❌ W0 | ⬜ pending |
| Constraint | Phase 13 scorer / `weight_config` / tier system byte-for-byte unchanged | regression | existing `test_skill.py` + `test_skill_scorer.py` stay green | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/integration/test_skill_dashboard.py` — covers Req 1, 3, 4, 5, 6, 7 (reuse the `seed` factory + `_recompute` helper pattern from `test_skill.py`).
- [ ] Extend `tests/services/test_skill_service.py` — covers Req 2 cause attribution (PLAYER/MAP split, coalesced→SYSTEM) with mocked repo; **extend the `_reset_guard` autouse fixture (`test_skill_service.py:51-59`) to also reset the new descriptor accumulator** or burst state leaks across tests.
- [ ] No new framework install — pytest infrastructure fully present.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.* The dashboard is API-only (no UI in this repo this phase); every endpoint contract, the cause-attribution split, and the drill-down conservation invariant are assertable in pytest against the test DB.

---

## Validation Sign-Off

- [ ] All tasks have `<acceptance_criteria>` mapping to a requirement above, or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers the two missing test files/extensions
- [ ] No watch-mode flags
- [ ] Feedback latency acceptable (quick run is seconds)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
