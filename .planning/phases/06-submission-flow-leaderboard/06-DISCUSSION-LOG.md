# Phase 6: Submission Flow & Leaderboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 6-Submission Flow & Leaderboard
**Areas discussed:** Per-cycle speed enforcement, Submission endpoint design, RabbitMQ event timing, History/archive scope

---

## Per-cycle Speed Enforcement

### Q1: What happens when a player submits a slower time?

| Option | Description | Selected |
|--------|-------------|----------|
| Accept all, leaderboard picks best | Every submission stored. Leaderboard DISTINCT ON picks fastest. Simple, no service-level validation. | |
| Reject slower submissions | Service checks existing best for cycle, raises error if not faster. Mirrors core.completions behavior. | ✓ |
| Update in place | One row per user per cycle, UPDATE if faster. Would need schema change. | |

**User's choice:** Reject slower submissions
**Notes:** None

### Q2: Should speed check and cross-write be a single transaction?

| Option | Description | Selected |
|--------|-------------|----------|
| Single transaction | acquire conn -> check speed -> insert -> cross-write -> commit. All-or-nothing. | ✓ |
| Separate steps | Insert tournament completion first, then cross-write separately. | |

**User's choice:** Single transaction
**Notes:** None

### Q3: What should the rejection error look like?

| Option | Description | Selected |
|--------|-------------|----------|
| New SlowerTimeError -> 409 Conflict | Add SlowerTimeError(TournamentsError) with context. Controller maps to 409. | ✓ |
| Reuse existing pattern -> 422 | Use 422 with generic validation error. | |
| You decide | Let Claude pick. | |

**User's choice:** New SlowerTimeError domain exception -> 409 Conflict
**Notes:** None

### Q4: Should the service validate cycle is active and map matches?

| Option | Description | Selected |
|--------|-------------|----------|
| Full validation | Checks cycle active, map matches, user exists. Specific domain exceptions. | ✓ |
| Rely on DB constraints | Let FK constraints handle it. | |

**User's choice:** Full validation with specific domain exceptions
**Notes:** None

---

## Submission Endpoint Design

### Q1: How should the endpoint resolve which cycle?

| Option | Description | Selected |
|--------|-------------|----------|
| POST /tournaments/cycles/{cycle_id}/submit | Explicit cycle in path. Bot already knows cycle_id. | ✓ |
| POST /tournaments/categories/{category_id}/submit | Auto-resolves active cycle from category. | |
| POST /tournaments/submit with cycle_id in body | Flat endpoint, cycle in body. | |

**User's choice:** POST /tournaments/cycles/{cycle_id}/submit
**Notes:** None

### Q2: Leaderboard endpoint path?

| Option | Description | Selected |
|--------|-------------|----------|
| GET /tournaments/cycles/{cycle_id}/leaderboard | Cycle-centric nesting. Consistent with submission. | ✓ |
| GET /tournaments/leaderboard?cycle_id=N | Query param approach. | |
| You decide | Let Claude pick. | |

**User's choice:** GET /tournaments/cycles/{cycle_id}/leaderboard
**Notes:** None

### Q3: Who calls the submission endpoint?

| Option | Description | Selected |
|--------|-------------|----------|
| Bot only (via API key) | Same as existing completions flow. Bot passes user_id. | ✓ |
| Both bot and direct API | Support both callers. | |

**User's choice:** Bot only via API key
**Notes:** None

### Q4: Add user submission lookup endpoint?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, add it | Useful for bot to check before showing form. | |
| Not needed now | Speed enforcement check handles it. | ✓ |
| You decide | Let Claude determine. | |

**User's choice:** Not needed now
**Notes:** None

---

## RabbitMQ Event Timing

### Q1: Publish TournamentCompletionCreatedEvent in Phase 6?

| Option | Description | Selected |
|--------|-------------|----------|
| Publish now, consume in Phase 9 | Wire up publish_message() now. Events queued until Phase 9. | |
| Defer to Phase 9 | Don't publish anything. Phase 9 adds both publish and consume. | ✓ |
| Publish but skip in tests | Same as option 1 with test bypass noted. | |

**User's choice:** Defer to Phase 9
**Notes:** None

---

## History/Archive Scope

### Q1: Detail level per past cycle?

| Option | Description | Selected |
|--------|-------------|----------|
| Cycle metadata + winner only | Lightweight. Full standings via leaderboard endpoint. | ✓ |
| Full leaderboard per cycle | Full ranked standings inline. Could be heavy. | |
| Metadata only, no winner | Just cycle dates, map, status. Two API calls for basic info. | |

**User's choice:** Cycle metadata + winner only
**Notes:** None

### Q2: History endpoint structure?

| Option | Description | Selected |
|--------|-------------|----------|
| GET /tournaments/cycles?status=completed | Flexible status filter. One endpoint for all cycle states. | ✓ |
| GET /tournaments/history | Dedicated history endpoint. | |
| GET /tournaments/categories/{id}/history | Category-scoped history. | |

**User's choice:** GET /tournaments/cycles?status=completed
**Notes:** None

### Q3: Support category_id filter?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, optional category_id query param | Filter by both status and category. | ✓ |
| No, just status filter | Keep it simple. | |

**User's choice:** Yes, optional category_id query param
**Notes:** None

### Q4: Pagination approach?

| Option | Description | Selected |
|--------|-------------|----------|
| Offset-based with limit/offset | Standard pattern. Matches existing codebase. | ✓ |
| Cursor-based | Better for large datasets but over-engineered here. | |

**User's choice:** Offset-based with limit/offset
**Notes:** None

---

## Claude's Discretion

- Exact domain exception class signatures (SlowerTimeError, CycleNotActiveError, MapMismatchError)
- Response struct for cycle listing with winner info
- Whether cycles list needs a dedicated repo method or reuses fetch_cycle_history
- Service method names for submission flow
- Pagination defaults
- Whether cycles list also returns active/pending cycles

## Deferred Ideas

None -- discussion stayed within phase scope.
