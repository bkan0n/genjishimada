---
phase: 9
slug: bot-queue-consumers-announcements
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-30
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest `>=8.3.5` + pytest-asyncio (auto mode) |
| **Config file** | `apps/api/pyproject.toml` (bot has no dedicated pytest config — bot unit tests live under `apps/api/tests/`) |
| **Quick run command** | `uv run --directory apps/api pytest <path> -p no:xdist` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~60–90 seconds (full suite) |

> **Constraint (MEMORY.md):** paths relative to `apps/api`. Multi-file targeted runs need `--no-testmon`; single-file runs are fine. Bot consumers are unit-tested by invoking the handler body directly with mocked `self.bot.api`, mocked resolved channel, and a fabricated event struct — the `@queue_consumer` wrapper's live-RabbitMQ path is not exercised in unit tests.

---

## Sampling Rate

- **After every task commit:** Run the single new test file for the task's behavior — `uv run --directory apps/api pytest <file> -p no:xdist`
- **After every plan wave:** Run `just test-api` (watch for documented pre-existing failures: `test_difficulty_exact_filter`, the category-filter xdist flake — NOT regressions)
- **Before `/gsd:verify-work`:** Full suite green (modulo documented pre-existing failures)
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

> Task IDs are placeholders until plans are finalized; the nyquist-auditor / executor binds them to concrete plan tasks. Behaviors and commands below are authoritative.

| Behavior | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|----------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| `cycle_started` consumer decodes event, fetches category+map, posts new-cycle embed | DSC-01 | — | Fetched data validated before embed render; failed fetch → DLQ, no partial post | unit | `pytest tests/bot/test_tournaments_handler.py -k cycle_started -p no:xdist` | ❌ W0 | ⬜ pending |
| `cycle_completed` consumer posts Top-3 results embed (no XP line) | DSC-02 | — | Embed within Discord limits; XP line absent (D-03) | unit | `pytest tests/bot/test_tournaments_handler.py -k results_embed -p no:xdist` | ❌ W0 | ⬜ pending |
| Strip champion role from ALL holders then grant to winner | DSC-03 / RWD-03 | — | Idempotent transfer; tolerates stale holders | unit | `pytest tests/bot/test_tournaments_handler.py -k champion_role -p no:xdist` | ❌ W0 | ⬜ pending |
| `winner_user_id is None` → strip from all holders, leave vacant | DSC-03 / RWD-03 | — | No grant when no winner (D-05) | unit | `pytest tests/bot/test_tournaments_handler.py -k champion_vacant -p no:xdist` | ❌ W0 | ⬜ pending |
| Role ops staggered to avoid Discord rate limits | DSC-03 / RWD-03 | — | Bounded concurrency / inter-op delay across simultaneous category transitions | unit | `pytest tests/bot/test_tournaments_handler.py -k stagger -p no:xdist` | ❌ W0 | ⬜ pending |
| Cycle-scoped idempotency: duplicate `message_id` skipped; claim released on failure | DSC-01/02 | — | At-least-once delivery does not double-post | unit | `pytest tests/bot/test_tournaments_handler.py -k idempotency -p no:xdist` | ❌ W0 | ⬜ pending |
| `Tournament` config struct decodes `[channels.tournament]` from both TOMLs | DSC-01/02 | — | `forbid_unknown_fields` honored; both dev/prod TOMLs parse | unit | `pytest tests/bot/test_config_tournament.py -p no:xdist` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `apps/api/tests/bot/test_tournaments_handler.py` — stubs for DSC-01, DSC-02, DSC-03, RWD-03, idempotency, staggering
- [ ] `apps/api/tests/bot/test_config_tournament.py` — TOML→struct decode for the new `[channels.tournament]` block
- [ ] Shared fixtures: fake guild/role/member trio + mock `APIService` returning `TournamentCategoryResponse` + `MapModel`
- [ ] Framework install: none — pytest already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live embed renders correctly in Discord (thumbnail, clickable workshop link, winner @mention) | DSC-01 / DSC-02 / DSC-03 | Discord rendering + real gateway not exercised in unit tests | Trigger a real cycle_started / cycle_completed event in dev; confirm embed visuals + winner ping in the announcements channel |
| Champion role actually moves on the live guild | DSC-03 / RWD-03 | Requires real Discord guild + role state | In dev guild, assign role to a test member, fire cycle_completed, confirm strip-all + grant-to-winner |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
