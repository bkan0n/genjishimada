# Phase 9: Bot Queue Consumers & Announcements - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-30
**Phase:** 9-Bot Queue Consumers & Announcements
**Areas discussed:** Announcement channel routing, Embed content & format, Champion role transfer behavior, Sourcing missing embed data

---

## Announcement channel routing

| Option | Description | Selected |
|--------|-------------|----------|
| One dedicated tournament channel | New `channels.tournament.announcements` config key; all categories post there | partial ✓ |
| Reuse channels.updates.announcements | Post into the existing general announcements channel; no new config | partial ✓ |
| Per-category channels | Separate channel per category; hardest to keep in sync | |

**User's choice:** "I'd like a dedicated channel setting but for now we can just use the general announcements channel value."
**Notes:** Resolved as a hybrid — add a dedicated config key (repointable later) but initialize it to the general announcements channel ID. No per-category routing.

---

## Embed content & format

### Standings count (results embed)
| Option | Description | Selected |
|--------|-------------|----------|
| Top 3 + winner highlight | Podium, compact | ✓ |
| Top 10 | More complete, longer | |
| Full standings | Risks embed limits | |

**User's choice:** Top 3 + winner highlight.

### Winner ping + XP line (results embed)
| Option | Description | Selected |
|--------|-------------|----------|
| Ping winner, show XP if available | Mention winner + XP-awarded line | |
| Ping winner, no XP line | Mention winner, drop XP detail | ✓ |
| No ping, show XP if available | Name as text, XP when sourceable | |

**User's choice:** Ping winner, no XP line.
**Notes:** Also resolves the XP-sourcing question — no XP data needed for announcements. Deliberate deviation from ROADMAP success criterion 2.

### New-cycle embed content
| Option | Description | Selected |
|--------|-------------|----------|
| Rich: name, difficulty, category, code link, ends-at | Informative | |
| Required only: name, difficulty, category | Leanest | |
| Rich + map thumbnail image | Most visual | ✓ |

**User's choice:** Rich + map thumbnail image.

---

## Champion role transfer behavior

### Previous holder
| Option | Description | Selected |
|--------|-------------|----------|
| Strip role from all current holders | Self-healing | ✓ |
| Track previous winner explicitly | Precise but brittle | |
| Only add, never remove | Role accumulates | |

**User's choice:** Strip role from all current holders.

### No winner (winner_user_id None)
| Option | Description | Selected |
|--------|-------------|----------|
| Strip role, leave vacant | Fresh slate | ✓ |
| Leave current holder in place | Stale champion | |
| Strip role + post 'no champion' note | Most transparent | |

**User's choice:** Strip role, leave vacant.

### Champion announcement (DSC-03)
| Option | Description | Selected |
|--------|-------------|----------|
| Fold into the results embed | One message per cycle | ✓ |
| Separate champion announcement | Two messages | |
| Results embed + DM to new champion | Most personal, DMs can fail | |

**User's choice:** Fold into the results embed.

---

## Sourcing missing embed data

| Option | Description | Selected |
|--------|-------------|----------|
| Bot fetches via API on event receipt | Consumer-only; reuse APIService | ✓ |
| Extend the published events | Widen outbox payload + SDK structs | |
| Hybrid | Cheap scalars in event, thumbnail fetched | |

**User's choice:** "You can fetch from already existing endpoints most likely." → bot fetches via existing API endpoints.
**Notes (user correction):** "Don't use partial for the map information. You can use the get maps endpoint with the code parameter for the map." → use `get_map(code=...)` → `MapResponse` (has `map_banner` thumbnail + `difficulty`), NOT `/maps/{code}/partial`. Category name + `champion_role_id` come from `GET /tournaments/categories/{category_id}`.

---

## Claude's Discretion

- Role-op staggering mechanism/interval to avoid Discord rate limits (success criterion 4).
- Cycle-scoped idempotency-key construction for the consumers (success criterion 5), aligned with the outbox key `tournament:{event_type}:{cycle_id}`.
- Exact APIService method names/signatures, handler/class names, and embed field layout/styling.

## Deferred Ideas

- Per-category announcement channels.
- Separate champion celebration embed / DM to the new champion.
- "XP awarded" line in the results embed (would need XP sourcing).
- Full / top-10 leaderboard in announcements (Phase 10 slash commands).
