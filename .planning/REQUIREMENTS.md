# Requirements: Tournament System

**Defined:** 2026-05-29
**Core Value:** Give the Genji Parkour community a persistent, competitive cycle that keeps players engaged week-over-week through fresh map challenges, leaderboard competition, and visible champion recognition.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Cycle Management

- [x] **CYCLE-01**: Automatic cycle transitions at scheduled times (pg_cron or API lifespan task)
- [ ] **CYCLE-02**: Configurable tournament categories with admin-defined difficulty groupings
- [ ] **CYCLE-03**: Per-category cycle frequency (weekly or biweekly)
- [x] **CYCLE-04**: Map blacklist with configurable N-week cooldown window
- [x] **CYCLE-05**: Random map selection from eligible pool per category each cycle
- [x] **CYCLE-06**: Pre-rolled next-cycle maps generated at cycle transition
- [x] **CYCLE-07**: Admin can preview, reroll, or explicitly choose next-cycle maps
- [ ] **CYCLE-08**: Category configuration locked during active cycles, changeable between cycles

### Submissions & Leaderboard

- [ ] **SUB-01**: Tournament completion submission with tier-then-time ranking (fully verified > partial)
- [ ] **SUB-02**: Separate tournaments.completions table with per-cycle speed enforcement (fresh slate)
- [ ] **SUB-03**: Cross-write to core.completions only when tournament time is strictly faster
- [ ] **SUB-04**: tournament_completion_id FK on core.completions for metadata linking
- [ ] **SUB-05**: Per-cycle tournament leaderboard endpoint
- [ ] **SUB-06**: Tournament history/archive endpoint with past cycles and results

### Rewards & Recognition

- [x] **RWD-01**: Flat participation XP bonus on first submission per cycle
- [x] **RWD-02**: Configurable placement-based XP bonuses (admin sets N tiers and amounts)
- [ ] **RWD-03**: Discord champion role per category, transferred to cycle winner
- [x] **RWD-04**: Weekly participation streak tracking (maintained by submitting in any category)
- [x] **RWD-05**: Streak-based XP bonuses at configurable streak thresholds

### Admin & API

- [ ] **ADM-01**: Admin API endpoints for tournament configuration CRUD
- [ ] **ADM-02**: Admin API endpoints for category management
- [ ] **ADM-03**: Admin Discord slash commands for tournament actions

### Discord Integration

- [ ] **DSC-01**: Automated new-cycle announcement with map details
- [ ] **DSC-02**: Automated cycle results announcement with standings
- [ ] **DSC-03**: Automated champion role transfer announcements

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Engagement & Analytics

- **ENG-01**: "Set during Tournament X" badge metadata on core completion responses
- **ENG-02**: Personal tournament stats/trends (improvement tracking across cycles)
- **ENG-03**: Category-specific all-time records (hall of fame)
- **ENG-04**: Tournament-specific Discord threads per cycle
- **ENG-05**: Live leaderboard updates in Discord (throttled embed updates)
- **ENG-06**: Countdown to cycle end (computed from cycle_end_at)
- **ENG-07**: Configurable announcement channel per category

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Seasons/time-boxed tournaments | Adds massive complexity; perpetual cycle first, seasons as a reporting layer later if needed |
| Manual/admin-triggered cycle transitions | Creates single point of failure; automatic only |
| Mid-cycle category changes | Unfair to participants who submitted under original rules |
| Bracket/elimination format | Time-trial competition, not head-to-head; brackets add complexity with zero value |
| ELO/skill rating system | Over-engineering for a community competition; raw times and rankings tell the full story |
| Multiple simultaneous tournaments | Splits community attention; one tournament with multiple categories suffices |
| Custom user-created tournaments | Dilutes official competition; admin-only configuration |
| Tournament-specific anti-cheat | Existing verification pipeline handles proof validation |
| Mobile/web tournament management UI | API + Discord bot is the pattern; web UI is a separate project |
| Map voting by players | Popularity bias; random selection ensures variety, admin reroll handles edge cases |
| Notification spam (per-submission updates) | Kills engagement through fatigue; announce cycle events only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CYCLE-01 | Phase 7 | Complete |
| CYCLE-02 | Phase 4 | Pending |
| CYCLE-03 | Phase 4 | Pending |
| CYCLE-04 | Phase 5 | Complete |
| CYCLE-05 | Phase 5 | Complete |
| CYCLE-06 | Phase 5 | Complete |
| CYCLE-07 | Phase 5 | Complete |
| CYCLE-08 | Phase 4 | Pending |
| SUB-01 | Phase 6 | Pending |
| SUB-02 | Phase 6 | Pending |
| SUB-03 | Phase 6 | Pending |
| SUB-04 | Phase 6 | Pending |
| SUB-05 | Phase 6 | Pending |
| SUB-06 | Phase 6 | Pending |
| RWD-01 | Phase 8 | Complete |
| RWD-02 | Phase 8 | Complete |
| RWD-03 | Phase 9 | Pending |
| RWD-04 | Phase 8 | Complete |
| RWD-05 | Phase 8 | Complete |
| ADM-01 | Phase 4 | Pending |
| ADM-02 | Phase 4 | Pending |
| ADM-03 | Phase 10 | Pending |
| DSC-01 | Phase 9 | Pending |
| DSC-02 | Phase 9 | Pending |
| DSC-03 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 25 total
- Mapped to phases: 25
- Unmapped: 0

---
*Requirements defined: 2026-05-29*
*Last updated: 2026-05-29 after roadmap creation*
