# Phase 10: Bot Slash Commands - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-30
**Phase:** 10-Bot Slash Commands
**Areas discussed:** Streak data source, Command structure, Category selection UX, Output format, `/info` content & time, Empty/error states, Reroll map-arg input

---

## Streak data source

| Option | Description | Selected |
|--------|-------------|----------|
| Add GET streak endpoint here | Thin route + service method + APIService wrapper; repo `fetch_streak` + `TournamentStreakResponse` already exist | ✓ |
| Defer streak command | Ship info/leaderboard/reroll now, move streak to a follow-up phase | |

**User's choice:** Add GET streak endpoint here.
**Notes:** Self-only (resolve invoking user); show current + max streak.

---

## Command structure

| Option | Description | Selected |
|--------|-------------|----------|
| One `/tournament` group | All four as subcommands of one group | partial |
| Flat top-level commands | Separate top-level commands | partial |
| Split player vs admin groups | Player under `/tournament`, admin elsewhere | partial |

**User's choice:** One `/tournament` group for **player** commands; admin command must live OUTSIDE the group due to Discord per-command permission limits. Admin reroll placed as a **flat top-level `/tournament-reroll`** command (chosen over a `/tournament-admin` group or reusing `/mod`).
**Notes:** Admin gate = **Mod OR Sensei** (inline role check → `UserFacingError`, per `moderator.py`), enforced bot-side since the bot uses its own API key.

---

## Category selection UX

| Option | Description | Selected |
|--------|-------------|----------|
| Show all, no arg | Show every active category at once | |
| Required category arg | User must pick a category each invocation | ✓ |
| Default + optional arg | Default to a primary category | |

**Category arg presentation:**

| Option | Description | Selected |
|--------|-------------|----------|
| Autocomplete from API | Dynamic choices via `list_categories` | ✓ |
| Free-text name/id | Plain string, bot resolves | |

**User's choice:** Required `category` arg on info/leaderboard/reroll, presented via API-backed autocomplete.
**Notes:** Streak takes no category (self-only).

---

## Output format

| Option | Description | Selected |
|--------|-------------|----------|
| Info/leaderboard public, streak/reroll ephemeral | Mixed visibility | |
| All ephemeral | Only invoker sees responses | ✓ |
| All public | Everything in-channel | |

**Leaderboard depth:**

| Option | Description | Selected |
|--------|-------------|----------|
| Top 10 | Single embed | |
| Top 10 + paginate (discord-ext-menus) | Paginated | |
| Full standings | All entries | |

**Embed styling:**

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse Phase-9 styling | Match announcement embeds | ✓ |
| Fresh per-command styling | Independent design | |

**User's choice:** All ephemeral; reuse Phase-9 embed styling; leaderboard **paginates using the user's own paginator class (`apps/bot/utilities/paginator.py`), explicitly NOT discord-ext-menus**.
**Notes:** Page size 10; `CompletionsLeaderboardPaginator` is the rendering analog. Existing leaderboard endpoint returns the full list (no pagination params).

---

## `/info` content & time

| Option | Description | Selected |
|--------|-------------|----------|
| Full rich card | Map, code link, difficulty, category, thumbnail, time | ✓ |
| Full card + submission count | Adds live submission count | |
| Minimal | Map, code link, time only | |

**Time format:**

| Option | Description | Selected |
|--------|-------------|----------|
| Discord relative timestamp | `<t:…:R>` | |
| Relative + absolute | `<t:…:R>` + `<t:…:F>` | ✓ |
| Computed duration string | Static "2d 14h left" | |

**User's choice:** Full rich card mirroring the Phase-9 new-cycle embed; time shown as relative + absolute Discord timestamps.

---

## Empty/error states

| Option | Description | Selected |
|--------|-------------|----------|
| Friendly ephemeral messages | Specific, friendly copy per case | ✓ |
| Generic UserFacingError | Standard short error per case | |

**No-streak case:**

| Option | Description | Selected |
|--------|-------------|----------|
| Treat as zero | Show 0/0 + encouragement | ✓ |
| Not-participated message | Message, no numbers | |

**User's choice:** Friendly ephemeral messages; no-streak treated as zero with an encouraging line.

---

## Reroll map-arg input

| Option | Description | Selected |
|--------|-------------|----------|
| Overwatch code (CodeAllTransformer) | Optional `code` arg via existing transformer | ✓ |
| Autocomplete eligible maps | Autocomplete restricted to eligible maps | |

**Reroll behavior (asked separately):**

| Option | Description | Selected |
|--------|-------------|----------|
| Reroll + show new map | Random reroll, reply shows result | |
| Confirm, then reroll | Confirmation button first | |
| Reroll + optional explicit map | Random by default + optional explicit map | ✓ |

**User's choice:** Random reroll by default + **optional explicit map** via Overwatch `code` (CodeAllTransformer → choose-map endpoint). Intentionally slightly broader than criterion 4.

---

## Claude's Discretion

- Exact streak endpoint path/signature and APIService wrapper names.
- `StaticPaginatorView` vs `ApiPaginatorView` for the leaderboard (leaning Static — endpoint returns full list).
- Whether the slash-command Cog lives in the existing `tournaments.py` or a sibling module (leaning same file).
- Embed field layout, exact copy strings, autocomplete result limits.

## Deferred Ideas

- Command-name variants (`/tournament current`, `/tournament lb`, `/tournament-admin` group).
- Streak lookup for other users.
- Live submission count on `/info`.
- Past-cycle / history browsing slash command.
- Confirmation step before reroll.
- Autocomplete of eligible maps for the reroll code arg.
