---
phase: 09-bot-queue-consumers-announcements
verified: 2026-05-31T03:00:00Z
status: human_needed
score: 10/10 must-haves verified
overrides_applied: 1
overrides:
  - must_have: "When a cycle completes, the bot posts a results embed with final standings, placements, and XP awarded"
    reason: "D-03 (CONTEXT.md) explicitly drops the XP line — XP is delivered separately via api.xp.grant (Phase 8). The embed shows Top-3 standings, a winner @mention, and the crowned Champion line. ROADMAP criterion 2 wording predates the D-03 user directive."
    accepted_by: "phase-context-D-03"
    accepted_at: "2026-05-30T00:00:00Z"
re_verification:
  previous_status: human_needed
  previous_score: 7/7
  gaps_closed:
    - "Tournament queues api.tournament.cycle_started / api.tournament.cycle_completed and their .dlq companions are now declared in infra/rabbitmq/definitions.json (4 entries, canonical api.xp.grant pair shape)"
    - "DLQ sweep hardened: _process_all_dlqs_once acquires a fresh channel per base queue inside the loop, so a NOT_FOUND on one .dlq cannot cascade ChannelInvalidStateError into other queues"
    - "ChannelNotFoundEntity guard added in _process_one_dlq: missing .dlq logs [!] and returns 0 instead of raising"
    - "apps/api/tests/bot/test_rabbit_dlq_sweep.py added with 4 passing isolation tests"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Trigger a test cycle_started event via RabbitMQ (or publish directly using amqplib) for an existing category+map in the dev guild, and observe the announcement channel"
    expected: "A rich embed posts in the configured tournament announcement channel showing the map name, a clickable workshop.codes link with the code, Difficulty and Category fields, a relative ends-at timestamp, and (when the map has a banner) a thumbnail image"
    why_human: "Embed rendering, thumbnail display, and actual channel resolution require a live Discord connection + bot instance — not inspectable via code analysis"
  - test: "Trigger a test cycle_completed event with 3+ standings entries and a winner_user_id that is a member of the dev guild"
    expected: "One message posts in the tournament channel: an embed with Top-3 podium using @mentions, a crowned Champion field, a winner ping as the message content, and no XP line anywhere in the embed. The winner gains the category's champion role; any prior holders lose it. allowed_mentions ensures no @everyone fires."
    why_human: "Live Discord role mutations, AllowedMentions enforcement, and actual embed rendering require a live guild and bot session"
  - test: "Trigger cycle_completed with winner_user_id=None (no winner scenario)"
    expected: "All current champion-role holders are stripped, no role is granted, the results embed posts with 'No submissions' in the podium and no champion/ping content"
    why_human: "Requires a live guild to verify actual role stripping"
  - test: "Publish a duplicate cycle_started or cycle_completed event with the same message_id as a previously processed event"
    expected: "The bot does NOT post a second announcement; idempotency claim prevents re-execution"
    why_human: "Requires live RabbitMQ + bot idempotency claim DB to validate end-to-end de-dupe"
  - test: "Rebuild and restart the RabbitMQ broker (docker compose -f docker-compose.local.yml up -d --build rabbitmq), restart the bot, and observe one full DLQ sweep interval (~60s)"
    expected: "No ChannelNotFoundEntity / Channel closed by RPC timeout log lines for api.tournament.cycle_started, api.tournament.cycle_completed, or api.xp.grant. The four tournament queues exist at broker boot from definitions.json."
    why_human: "Broker reload + live log observation cannot be verified by static code analysis; confirms Part A (definitions.json) is applied at runtime"
---

# Phase 9: Bot Queue Consumers & Announcements — Verification Report

**Phase Goal:** The Discord bot reacts to tournament events — announcing new cycles, posting results, and transferring champion roles
**Verified:** 2026-05-31
**Status:** human_needed
**Re-verification:** Yes — after gap closure (Plan 09-03 closed the prior UAT Test-1 defect)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | When a new cycle starts, the bot posts an announcement embed with map name, difficulty, and category | VERIFIED | `_on_cycle_started` (tournaments.py:84-109) fetches category + map, builds embed with Difficulty/Category fields, clickable workshop-code link, ends_at timestamp, banner thumbnail; `test_cycle_started_posts_new_cycle_embed` and `test_cycle_started_no_thumbnail_when_banner_none` PASSED |
| 2 | When a cycle completes, the bot posts a results embed with final standings, placements, and winner highlight (XP line deliberately omitted per D-03) | PASSED (override) | `_on_cycle_completed` posts Top-3 podium + champion field + winner ping; grep confirms 0 occurrences of "xp awarded" in tournaments.py; override applied for D-03 XP deviation |
| 3 | The champion Discord role for each category is removed from all holders and granted to the winner | VERIFIED | `_transfer_champion_role` (tournaments.py:167-239): strips ALL role.members with per-member try/except + reason + stagger, grants to guild.get_member(winner_user_id); tests `test_champion_role_transfer_strips_all_then_grants` and `test_champion_vacant_when_no_winner` PASSED |
| 4 | Role operations are staggered to respect Discord rate limits | VERIFIED | `_ROLE_OP_DELAY = 1.0` at line 59; `await asyncio.sleep(_ROLE_OP_DELAY)` at line 211 after each remove_roles; `test_role_ops_stagger_to_respect_rate_limits` PASSED |
| 5 | Queue consumers use cycle-scoped idempotency to prevent duplicate announcements | VERIFIED | Both consumers decorated with `@queue_consumer(..., idempotent=True)` (lines 79-83, 111-115); `test_idempotency_skips_duplicate_and_releases_claim_on_failure` PASSED |
| 6 | The TournamentHandler is registered as a PUBLIC bot.tournaments attribute so RabbitHandler discovers the consumers | VERIFIED | `setup()` (tournaments.py:469-480) does `bot.tournaments = TournamentHandler(bot)`; genji.py:143-149 exposes public `@property tournaments` + setter; `from extensions.tournaments import TournamentHandler` at genji.py:17 |
| 7 | D-01: channels.tournament.announcements config resolves per-environment from both TOMLs | VERIFIED | dev.toml line 64: `announcements = 1377808369997447254`; prod.toml line 64: `announcements = 975820285343301674`; `Tournament(Base)` struct at config.py:89-90; `Channels.tournament: Tournament` at config.py:99; config decode tests PASSED |
| 8 | The tournament queues and their .dlq companions are declared in definitions.json | VERIFIED | 6 lines in definitions.json match `"api.tournament`; all 4 entries confirmed: main queues carry `x-dead-letter-exchange: ""` + own-name `.dlq` routing key; `.dlq` entries carry only `x-queue-type: classic`; python3 JSON parse exits 0 |
| 9 | The DLQ sweep is resilient — a single failing .dlq cannot cascade ChannelInvalidStateError across the sweep | VERIFIED | `_process_all_dlqs_once` (rabbit.py:264-283) acquires channel INSIDE the for loop (line 278); `ChannelNotFoundEntity` imported (line 11) and guarded in `_process_one_dlq` (line 302); 4/4 isolation tests PASSED |
| 10 | Main-queue argument parity: definitions.json tournament arguments match bot's _set_up_queues declaration | VERIFIED | Both main queues carry `x-dead-letter-exchange: ""`, `x-dead-letter-routing-key: <queue>.dlq`, `x-queue-type: classic` — identical to bot runtime declaration (rabbit.py:85-94); no PRECONDITION_FAILED expected |

**Score:** 10/10 truths verified (1 via override for the deliberate D-03 XP-line deviation)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `apps/bot/extensions/tournaments.py` | TournamentHandler with two @queue_consumer(idempotent=True) methods, both embeds, role transfer, setup() | VERIFIED | 481 lines; class TournamentHandler at line 68, both @queue_consumer decorators with idempotent=True at lines 79-83 and 111-115, _transfer_champion_role at 167, setup() at 469 registering `bot.tournaments = TournamentHandler(bot)` |
| `apps/bot/core/genji.py` | public tournaments @property/@setter + _tournament_manager attr + import | VERIFIED | Line 17: `from extensions.tournaments import TournamentHandler`; line 45: `_tournament_manager: TournamentHandler`; lines 143-149: public `@property tournaments` + `@tournaments.setter` |
| `apps/bot/extensions/api_service.py` | get_tournament_category wrapper | VERIFIED | Line 1674: `def get_tournament_category(self, category_id: int) -> Response[TournamentCategoryResponse]`; builds `Route("GET", "/tournaments/categories/{category_id}", ...)`, calls `self._request(r, response_model=TournamentCategoryResponse)`; TournamentCategoryResponse imported at line 102 |
| `apps/bot/utilities/config.py` | Tournament(Base) struct + Channels.tournament field | VERIFIED | Lines 89-90: `class Tournament(Base): announcements: int`; line 99: `tournament: Tournament` in Channels struct |
| `apps/bot/configs/dev.toml` | [channels.tournament] block with dev announcements id | VERIFIED | Lines 63-64: `[channels.tournament]\nannouncementes = 1377808369997447254` |
| `apps/bot/configs/prod.toml` | [channels.tournament] block with prod announcements id | VERIFIED | Lines 63-64: `[channels.tournament]\nannouncements = 975820285343301674` |
| `infra/rabbitmq/definitions.json` | 4 tournament queue+DLQ declarations | VERIFIED | Lines 355-394: all 4 entries present with canonical arg shape matching api.xp.grant pair |
| `apps/bot/extensions/rabbit.py` | Hardened _process_all_dlqs_once + ChannelNotFoundEntity guard | VERIFIED | Channel acquisition inside the for loop (line 278); ChannelNotFoundEntity imported (line 11) and guarded in _process_one_dlq (line 302) |
| `apps/api/tests/bot/test_rabbit_dlq_sweep.py` | 4 isolation unit tests | VERIFIED | 4 tests all PASSED: sweep_isolates_failure, sweep_returns_total, missing_dlq_skips_cleanly, sweep_acquires_fresh_channel_per_base_queue |
| `apps/api/tests/bot/__init__.py` | Bot test package marker | VERIFIED | File exists |
| `apps/api/tests/bot/conftest.py` | Shared FakeGuild/FakeRole/FakeMember + mock APIService fixtures | VERIFIED | FakeMember (records add_roles/remove_roles), FakeRole (mutable members), FakeGuild (get_role/get_member), mock_api AsyncMock returning sample_category + sample_map |
| `apps/api/tests/bot/test_config_tournament.py` | TOML decode test for [channels.tournament] | VERIFIED | 3 tests: dev decode, prod decode, forbid_unknown_fields — all PASSED |
| `apps/api/tests/bot/test_tournaments_handler.py` | Handler behavior tests — all green, 0 xfail | VERIFIED | 10/10 PASSED: cycle_started (2), results_embed (2), champion_role (4), stagger (1), idempotency (1) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tournaments.py setup()` | `genji.py bot.tournaments` | `bot.tournaments = TournamentHandler(bot)` | WIRED | Line 478 of tournaments.py; genji.py property at line 143; public attr confirms RabbitHandler public-attr scan will find consumers |
| `tournaments.py _on_cycle_started` | `api.tournament.cycle_started` queue | `@queue_consumer("api.tournament.cycle_started", ..., idempotent=True)` | WIRED | Lines 79-83; decorator sets `_queue_name` on the method for rabbit.py discovery |
| `tournaments.py _on_cycle_completed` | `api.tournament.cycle_completed` queue | `@queue_consumer("api.tournament.cycle_completed", ..., idempotent=True)` | WIRED | Lines 111-115; same discovery mechanism |
| `tournaments.py champion transfer` | guild role membership | `guild.get_role(category.champion_role_id)` + `remove_roles` / `add_roles` | WIRED | Lines 188, 204, 229; champion_role_id sourced from TournamentCategoryResponse (not event) |
| `api_service.py get_tournament_category` | `GET /tournaments/categories/{category_id}` | `Route("GET", "/tournaments/categories/{category_id}", category_id=category_id)` | WIRED | Lines 1674-1681; matches verified API route |
| `dev.toml [channels.tournament]` | `config.py Tournament struct` | `msgspec.toml.decode` with `forbid_unknown_fields=True` | WIRED | Config decode test PASSED; Tournament struct is a Base subclass with forbid_unknown_fields honored |
| `definitions.json api.tournament.cycle_started` | `api.tournament.cycle_started.dlq` | `x-dead-letter-routing-key` argument | WIRED | Line 362: `"x-dead-letter-routing-key": "api.tournament.cycle_started.dlq"` |
| `rabbit.py _process_all_dlqs_once loop` | per-base-queue channel isolation | fresh channel acquired inside the for loop | WIRED | Line 278: `async with self._channel_pool.acquire() as channel:` is INSIDE `for base_queue in self._queues:` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `tournaments.py _on_cycle_started` | `category` (name, champion_role_id) | `get_tournament_category(event.category_id)` → GET /tournaments/categories/{id} → DB | Yes — API fetches from DB on event receipt | FLOWING |
| `tournaments.py _on_cycle_started` | `map_data` (difficulty, map_name, map_banner) | `get_map(code=event.map_code)` → GET /maps (full endpoint, not /partial) → DB | Yes — API fetches full MapResponse with banner field | FLOWING |
| `tournaments.py _on_cycle_completed` | `event.standings[:3]` | Decoded from TournamentCycleCompletedEvent payload body (set by Phase 7 outbox) | Yes — standings are real leaderboard data from Phase 7 | FLOWING |
| `tournaments.py _on_cycle_completed` | `category.champion_role_id` | `get_tournament_category(event.category_id)` → API | Yes — role ID comes from tournaments.categories DB record | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 28 bot tests pass (handler + config + dlq sweep + commands) | `uv run --directory apps/api pytest tests/bot/ --no-testmon -p no:xdist` | 28 passed in 6.27s | PASS |
| 4 DLQ sweep isolation tests pass | `uv run --directory apps/api pytest tests/bot/test_rabbit_dlq_sweep.py --no-testmon -p no:xdist` | 4 passed in 2.72s | PASS |
| No "XP awarded" string in results embed code | `grep -v '^#' apps/bot/extensions/tournaments.py \| grep -ic "xp awarded"` | 0 | PASS |
| Both queue consumers use idempotent=True | `grep -n '@queue_consumer\|idempotent=True' tournaments.py` | Lines 79-83, 111-115 both have idempotent=True | PASS |
| setup() registers as PUBLIC bot.tournaments | `grep -n "bot.tournaments\s*="` | Line 478: `bot.tournaments = TournamentHandler(bot)` | PASS |
| _ROLE_OP_DELAY stagger between ops | `grep -n "_ROLE_OP_DELAY\|asyncio.sleep" tournaments.py` | Line 59 defines constant 1.0; line 211 awaits sleep | PASS |
| Channel acquired INSIDE the sweep loop | `grep -n "async with self._channel_pool" rabbit.py` | Line 278 (inside for loop); line 137 is a separate unrelated context | PASS |
| All 4 tournament queue entries present in definitions.json | `python3 -c "import json,sys; d=json.load(...)..."` | ALL PRESENT | PASS |
| definitions.json is valid JSON | `python3 -c "import json; json.load(open('infra/rabbitmq/definitions.json'))"` | Exits 0 | PASS |

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes declared or present for this phase. Phase is a bot extension (not a migration/CLI/tooling phase). Probe section: SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| DSC-01 | 09-01-PLAN.md, 09-02-PLAN.md | Automated new-cycle announcement with map details | SATISFIED | `_on_cycle_started` posts embed with map name, difficulty, category, clickable workshop link, ends_at, thumbnail; test PASSED; queue declared in definitions.json |
| DSC-02 | 09-01-PLAN.md, 09-02-PLAN.md | Automated cycle results announcement with standings | SATISFIED | `_on_cycle_completed` posts Top-3 podium embed + winner ping; test PASSED; XP line omission is intentional D-03 deviation |
| DSC-03 | 09-02-PLAN.md, 09-03-PLAN.md | Automated champion role transfer announcements | SATISFIED | Champion transfer folded into results embed (D-06); role stripped from all holders, granted to winner; test PASSED; queue infrastructure hardened |
| RWD-03 | 09-02-PLAN.md, 09-03-PLAN.md | Discord champion role per category, transferred to cycle winner | SATISFIED | `_transfer_champion_role` strips ALL role.members then grants to winner; self-healing, D-04/D-05 honored; test PASSED; DLQ resilience prevents cascade failures from blocking future transfers |

No orphaned requirements: all four IDs (DSC-01, DSC-02, DSC-03, RWD-03) are declared in plan frontmatter, verified in code, and marked Complete in REQUIREMENTS.md traceability table.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | — |

No TBD, FIXME, or XXX markers in any phase-modified file. No stub return values. No placeholder text. The docstring phrase "deliberately omits any experience-points line" is intentional documentation of the D-03 design decision, not a stub.

### Human Verification Required

#### 1. New-Cycle Embed — Live Discord Render

**Test:** Trigger a `api.tournament.cycle_started` message (with a valid category_id and map_code from the dev DB) against the running bot in the dev guild, observe the configured tournament announcement channel.
**Expected:** A rich embed appears with the map name hyperlinking to `https://workshop.codes/{code}`, the raw code in a code-span, Difficulty and Category fields matching the DB data, a relative "Ends in X days" timestamp, and a thumbnail image (when the map has a banner).
**Why human:** Embed field rendering, thumbnail display, correct channel resolution, and Discord API round-trip cannot be verified by static code analysis or offline test fixtures.

#### 2. Cycle Results Embed + Champion Role Transfer — Live Discord Round-Trip

**Test:** Trigger a `api.tournament.cycle_completed` message with 3+ standings entries and a `winner_user_id` corresponding to a real guild member who does NOT already hold the champion role. Inspect the channel and the winner's roles.
**Expected:** One message posts (not two) with the Top-3 podium using @mentions, a "crowned Champion of {category}!" field, a winner ping in the message content, and no XP text anywhere. The winner gains the category's champion role; any prior holders lose it. `allowed_mentions` ensures no @everyone fires.
**Why human:** Live Discord role mutations, AllowedMentions enforcement, and the "one send" ordering constraint (Pitfall 5) require an active bot session and guild state.

#### 3. Vacant Cycle (No Winner) — Role Stripping Without Grant

**Test:** Trigger `cycle_completed` with `winner_user_id=null` for a category where one or more members currently hold the champion role.
**Expected:** The champion role is stripped from all current holders; no new grant occurs; the results embed posts with "No submissions" in the podium and no champion/ping content.
**Why human:** Requires live guild with current champion-role holders to observe the strip.

#### 4. Duplicate-Event Idempotency — End-to-End De-Duplication

**Test:** Process a cycle_started event normally (bot posts announcement), then re-publish the same message (same `message_id` as the original outbox record) to the queue.
**Expected:** The bot does NOT post a second announcement. The idempotency claim in `public.idempotency_claims` prevents the handler body from executing.
**Why human:** Requires live RabbitMQ + the API's idempotency claim DB table to verify the full claim/skip/release path end-to-end. The unit test covers the wrapper logic in isolation; this tests the full stack.

#### 5. DLQ Sweep Clean After Broker Reload (09-03 Operational Verification)

**Test:** Rebuild and restart the RabbitMQ broker (`docker compose -f docker-compose.local.yml up -d --build rabbitmq`), restart the bot, and observe one full DLQ sweep interval (default 60s) in the bot logs.
**Expected:** No `ChannelNotFoundEntity` / `Channel closed by RPC timeout` log lines for `api.tournament.cycle_started`, `api.tournament.cycle_completed`, or `api.xp.grant`. The tournament queues exist at broker boot from the new definitions.json entries.
**Why human:** Broker reload + live log observation cannot be verified by static code analysis. This confirms the definitions.json Part A fix is actually applied at broker boot time and that the four new entries are syntactically valid as parsed by the RabbitMQ management plugin. The unit tests prove code-level resilience; this confirms the infrastructure fix end-to-end.

### Gaps Summary

No code-level gaps remain. All 10 must-haves are verified:

- Plans 09-01 and 09-02 (7 truths): fully verified in the prior verification (7/7 PASSED).
- Plan 09-03 (3 additional truths): verified now — the four tournament queue+DLQ declarations are present in definitions.json with the canonical argument shape; the DLQ sweep acquires a fresh channel per base queue inside the loop; the ChannelNotFoundEntity guard skips missing .dlq entries cleanly; 4/4 isolation unit tests pass.

Five items require a human operator with a live bot session and/or broker. These are standard for bot-extension phases (live embed rendering, live role mutations, live idempotency claim database, broker reload observation). All automated-verifiable code properties have been confirmed.

---

_Verified: 2026-05-31_
_Verifier: Claude (gsd-verifier)_
