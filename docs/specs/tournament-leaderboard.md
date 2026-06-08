# Tournament Leaderboard Spec

## Overview

A tournament system where players compete on maps within a tournament context. Tournament completions have their own leaderboard and speed enforcement, but fast tournament times also appear on the normal completions leaderboard.

## Data Model

### New Table: `tournaments.tournaments`

Top-level tournament definition.

| Column | Type | Notes |
|--------|------|-------|
| id | int (identity) | PK |
| name | text | Tournament name |
| ... | ... | TBD: start/end dates, status, rules, etc. |

### New Table: `tournaments.completions`

Mirrors `core.completions` schema plus tournament-specific fields.

| Column | Type | Notes |
|--------|------|-------|
| id | int (identity) | PK |
| tournament_id | int | FK -> tournaments.tournaments |
| map_id | int | FK -> core.maps |
| user_id | bigint | FK -> core.users |
| time | numeric(10,2) | Completion time |
| screenshot | text | NOT NULL |
| video | text | Optional |
| completion | boolean | Completion flag |
| inserted_at | timestamptz | Default now() |
| ... | ... | Other shared columns as needed |

### Modified Table: `core.completions`

Add a nullable FK to link back to the tournament entry when cross-written.

| Column | Type | Notes |
|--------|------|-------|
| tournament_completion_id | int, nullable | FK -> tournaments.completions, NULL for normal submissions |

## Speed Enforcement

### Within Tournament

- Each tournament is a **fresh slate** -- no relation to the user's `core.completions` times.
- Standard "must be strictly faster" enforcement applies within the tournament table for the same `(tournament_id, map_id, user_id)`.
- A user's first tournament submission for a map is always accepted.
- Subsequent submissions must be strictly faster than their current best **in that tournament**.

### Cross-Write to `core.completions`

On each tournament submission:

1. Fetch the user's current best time in `core.completions` for that map.
2. If no existing entry, or if the tournament time is strictly faster: insert into `core.completions` with `tournament_completion_id` set.
3. If the tournament time is equal or slower: skip the cross-write. No error.

This preserves the existing "latest = fastest" invariant in `core.completions`, so **no leaderboard query changes are needed**.

The cross-write happens at submission time (not batched at tournament end) so normal leaderboards stay live.

## Leaderboards

### Tournament Leaderboard

- Queries `tournaments.completions` filtered by `tournament_id`.
- Shows each user's best (latest, since enforcement guarantees latest = fastest) time per map.
- Separate from the normal completions leaderboard.

### Normal Completions Leaderboard

- No changes to existing queries.
- Tournament-sourced entries appear naturally via the cross-write.
- The `tournament_completion_id` FK allows UI to indicate "this time was set during tournament X" and link to tournament details (participants, results, etc.).

## Metadata Linking

From a `core.completions` record with `tournament_completion_id IS NOT NULL`:

- Join to `tournaments.completions` to get the tournament entry.
- Join to `tournaments.tournaments` to get tournament name, dates, participants.
- Enables UI features like "Set during [Tournament Name]" badges on leaderboard entries.

## Open Questions

- Tournament table details: start/end dates, status lifecycle, map pool definition.
- What happens to tournament leaderboard data after a tournament ends? Archived? Always visible?
- Can a map appear in multiple active tournaments simultaneously?
- Verification flow: do tournament completions go through the same verification pipeline as normal completions?
- Should the cross-write also trigger downstream events (XP, notifications, world record checks)?
