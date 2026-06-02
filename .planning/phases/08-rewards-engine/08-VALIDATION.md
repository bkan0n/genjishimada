---
phase: 8
slug: rewards-engine
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-30
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (pytest-asyncio auto, pytest-databases[postgres]) |
| **Config file** | `apps/api/pyproject.toml` |
| **Quick run command** | `uv run --directory apps/api pytest tests/services/test_tournament_reward_service.py tests/integration/test_tournament_rewards.py -p no:xdist -q` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~60 seconds (quick) / parallel full suite |

---

## Sampling Rate

- **After every task commit:** Run quick command scoped to touched test module
- **After every plan wave:** Run `just test-api`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| T1 Migration 0022 ledger | 08-01 | 1 | RWD-01/02/04/05 | T-08-01 | UNIQUE(cycle,user,reason) double-grant guard | schema (grep gate) | `grep -q "UNIQUE (cycle_id, user_id, reason)" apps/api/migrations/0022_tournament_xp_grants.sql && grep -q "user_id     bigint\|user_id bigint" apps/api/migrations/0022_tournament_xp_grants.sql && grep -q "reason IN ('participation', 'placement', 'streak')" apps/api/migrations/0022_tournament_xp_grants.sql` | ❌ W0 | ⬜ pending |
| T2 XP_TYPES "Tournament" | 08-01 | 1 | RWD-01/02/05 | — | analytics distinguishability | unit (import assert) | `grep -q '"Tournament"' libs/sdk/src/genjishimada_sdk/xp.py && uv run --directory apps/api python -c "from genjishimada_sdk.xp import XP_TYPES; import typing; assert 'Tournament' in typing.get_args(XP_TYPES)"` | ❌ W0 | ⬜ pending |
| T3 Reward repo methods + scaffolds | 08-01 | 1 | RWD-01/02/04/05 | T-08-01, T-08-02 | ledger claim + dedupe-guarded streak | unit + scaffold collect | `uv run --directory apps/api pytest tests/services/test_tournament_reward_service.py tests/integration/test_tournament_rewards.py -p no:xdist -q && grep -q "def claim_xp_grant" apps/api/repository/tournaments_repository.py && grep -q "def advance_streak" apps/api/repository/tournaments_repository.py && grep -q "def fetch_cycle_participants" apps/api/repository/tournaments_repository.py && grep -q "def fetch_all_streak_user_ids" apps/api/repository/tournaments_repository.py` | ❌ W0 | ⬜ pending |
| T1 grant_xp conn helper | 08-02 | 2 | RWD-01/02/05 | T-08-05 | shared-txn ledger+upsert atomicity | unit (service) | `uv run --directory apps/api pytest tests/services/test_lootbox_service.py -p no:xdist -q && grep -q "async def grant_xp" apps/api/services/lootbox_service.py` | ❌ W0 | ⬜ pending |
| T2 TournamentRewardService | 08-02 | 2 | RWD-01/02/05 | T-08-04, T-08-06 | ledger guard + generic XpGrantEvent only | unit (service) | `uv run --directory apps/api pytest tests/services/test_tournament_reward_service.py -p no:xdist -q && grep -q "class TournamentRewardService" apps/api/services/tournament_reward_service.py && ! grep -q "TournamentXpGrantEvent" apps/api/services/tournament_reward_service.py` | ❌ W0 | ⬜ pending |
| T3 Reward service unit tests | 08-02 | 2 | RWD-01/02/05 | T-08-04 | once-per-(cycle,user); tie/beyond-tier/empty | unit (service) | `uv run --directory apps/api pytest tests/services/test_tournament_reward_service.py -p no:xdist -q -k "participation or placement or streak"` | ❌ W0 | ⬜ pending |
| T1 Participation hook + DI wiring | 08-03 | 3 | RWD-01 | T-08-09 | existing-is-None gate + ledger; app boots | unit + integration + boot | `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournaments_integration.py -p no:xdist -q && grep -q "award_participation" apps/api/services/tournament_service.py && uv run --directory apps/api python -c "from app import app"` | ❌ W0 | ⬜ pending |
| T2 Outbox cycle-end hook + reset sweep | 08-03 | 3 | RWD-02/04/05 | T-08-08, T-08-11 | award_cycle_end + reset sweep in outbox txn | integration | `uv run --directory apps/api pytest tests/integration/test_tournament_rewards.py -p no:xdist -q && grep -q "award_cycle_end" apps/api/services/tournament_outbox_service.py && grep -q "fetch_all_streak_user_ids" apps/api/services/tournament_outbox_service.py` | ❌ W0 | ⬜ pending |
| T3 Integration tests (streak/dedupe/double-grant) | 08-03 | 3 | RWD-04 + double-grant | T-08-08, T-08-10 | replay no-dup; multi-category single increment; reset to 0 | integration (real DB) | `uv run --directory apps/api pytest tests/integration/test_tournament_rewards.py -p no:xdist -q -k "streak or idempot or reset or dedupe"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `apps/api/tests/services/test_tournament_reward_service.py` — unit-test scaffold (created in 08-01 Task 3), filled by 08-02 Task 3; covers RWD-01, RWD-02, RWD-05 (mocked publish seam)
- [ ] `apps/api/tests/integration/test_tournament_rewards.py` — integration-test scaffold (created in 08-01 Task 3), filled by 08-03 Task 3; covers RWD-04, streak reset, multi-category dedupe, double-grant (real DB)
- [ ] Migration `0022_tournament_xp_grants.sql` (08-01 Task 1) must be applied by the test DB fixture (the conftest migration glob picks up new migrations automatically, as it did for 0020/0021)
- [ ] After the `XP_TYPES` edit (08-01 Task 2): run `just fix` so the workspace SDK is reinstalled before tests (per MEMORY.md SDK-import note)

*Existing pytest infrastructure covers the framework; the two new test modules are the Wave 0 deliverable, scaffolded in 08-01 and filled in 08-02/08-03.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end XP credited in bot rank card | RWD-02 | Bot consumer is Phase 9 (not built) | Verify `XpGrantEvent` published to `api.xp.grant` with correct payload via integration test asserting publish args |

*All API-side reward invariants (once-per-cycle, streak increment/reset, double-grant prevention, placement tier mapping) have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
</content>
