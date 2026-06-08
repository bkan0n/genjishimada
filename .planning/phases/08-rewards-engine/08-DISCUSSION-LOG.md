# Phase 8: Rewards Engine — DISCUSSION LOG

**Mode:** `--auto` (autonomous; recommended option chosen for every question, no interactive prompts)
**Date:** 2026-05-30

> Human-reference audit trail only. Downstream agents read `08-CONTEXT.md`.

## Gray areas selected
`[--auto] Selected all gray areas: Participation XP trigger, Placement XP computation, Streak tracking, Streak bonus config, Double-grant prevention, Reward payload shape.`

## Area: Participation XP
- Q: Where is participation XP awarded?
  - Options: (rec) inside existing submit path / separate post-hoc batch job / bot-side
  - Selected: **inside `TournamentService.submit`, on first completion in cycle** (recommended)
- Q: How is once-per-cycle enforced?
  - Options: (rec) DB-state guard (no prior completion for user+cycle) / queue idempotency key / counter column
  - Selected: **DB-state guard** (recommended)

## Area: Placement XP
- Q: Where/when computed?
  - Options: (rec) API service at cycle finalization (Phase-7 outbox flow) / SQL transition function / bot
  - Selected: **API service at finalization, reusing Phase-7 outbox** (recommended)
- Q: SQL or Python for tier→amount mapping?
  - Options: (rec) Python / SQL
  - Selected: **Python** (recommended)

## Area: Streak tracking
- Q: When updated?
  - Options: (rec) at cycle-end finalization / on each submission / nightly job
  - Selected: **at cycle-end finalization** (recommended)
- Q: What counts as participation?
  - Options: (rec) ≥1 category submission that cycle / all categories / verified only
  - Selected: **≥1 category submission** (recommended)

## Area: Streak bonus
- Q: Where configured?
  - Options: (rec) `tournaments.xp_config` / new table / hardcoded
  - Selected: **`tournaments.xp_config`** (recommended)
- Q: When granted?
  - Options: (rec) same finalization step on threshold crossing / separate pass
  - Selected: **same finalization step** (recommended)

## Area: Double-grant prevention
- Q: How avoid double XP on retry?
  - Options: (rec) DB-recorded award state + deterministic cycle-scoped keys / rely on queue idempotency
  - Selected: **DB-recorded award state + deterministic keys** (recommended; `api.xp.grant` is non-idempotent)

## Area: Reward payload shape
- Q: New struct or reuse `api.xp.grant`?
  - Options: (rec) reuse with reason/source discriminator / new event struct
  - Selected: **reuse `api.xp.grant`** (recommended)

## Deferred ideas
- Champion role transfer (RWD-03) → Phase 9
- Results/XP announcements → Phase 9
- "Set during Tournament X" badge (ENG-01) → v2
- Streak/stats slash command → Phase 10

## Claude's discretion / flagged for research
- Confirm exact `TournamentService` / `TournamentRepository` filenames.
- Confirm `tournaments.streaks` / `tournaments.xp_config` columns (may need thin additive migration).
- Confirm existing `api.xp.grant` payload shape.
- Confirm how to extend the Phase-7 outbox poller / transition for reward emission.
