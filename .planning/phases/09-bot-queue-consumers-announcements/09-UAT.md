---
status: diagnosed
phase: 09-bot-queue-consumers-announcements
source: [09-01-SUMMARY.md, 09-02-SUMMARY.md]
started: 2026-05-30T22:39:23Z
updated: 2026-05-31T01:56:31Z
---

## Current Test

[testing paused — 5 items outstanding; stopped to diagnose Test 1 DLQ defect]

## Tests

### 1. New-Cycle Announcement Embed
expected: When a tournament cycle starts, the bot posts one embed in the configured tournament announcements channel showing map name, a clickable workshop.codes link + raw code, Difficulty and Category fields, the cycle end time as a relative timestamp, and the map banner as a thumbnail.
result: issue
reported: "Bot runtime error: aiormq.exceptions.ChannelNotFoundEntity: NOT_FOUND - no queue 'api.tournament.cycle_completed.dlq' in vhost '/'. DLQ processor fails for the new tournament queues every sweep; the channel-close then cascades into 'Channel closed by RPC timeout' for api.tournament.cycle_started and api.xp.grant in the same loop."
severity: major

### 2. Results Embed (Top-3 Podium, No XP Line)
expected: When a cycle completes with submissions, the bot posts ONE results embed showing a Top-3 podium that pings winners via numeric user mentions (not free-text names), a "crowned Champion of {category}" field with the winner ping, and NO experience-points / XP line. With no submissions, the podium shows "No submissions".
result: [pending]

### 3. Champion Role Transfer to Winner
expected: On cycle completion with a winner, the category champion Discord role is stripped from ALL prior holders and granted to the winner. The role transfer happens FIRST, then the single results message is sent LAST. Only the winner is actually pinged (AllowedMentions blocks @everyone/role pings).
result: [pending]

### 4. Vacant Cycle (No Winner)
expected: When a cycle completes with no winner (winner_user_id is None), the champion role is stripped from all current holders and left vacant (granted to no one), and the results embed still posts with the empty/"No submissions" podium handling.
result: [pending]

### 5. Duplicate-Event De-duplication
expected: Redelivery of the same cycle event (same idempotency message_id) does NOT post a duplicate announcement or run a second role transfer — the idempotency claim short-circuits the handler body.
result: [pending]

### 6. Announcements Channel Repointability
expected: The tournament announcements channel is driven by config.channels.tournament.announcements (separate per-environment key). Changing that channel id in the env config and restarting the bot routes the announcements to the new channel without code changes.
result: [pending]

## Summary

total: 6
passed: 0
issues: 1
pending: 5
skipped: 0
blocked: 0

## Gaps

- truth: "The bot runs cleanly while consuming the tournament queues; the DLQ processor sweep does not error for api.tournament.cycle_started / api.tournament.cycle_completed."
  status: failed
  reason: "User reported: bot logs `aiormq.exceptions.ChannelNotFoundEntity: NOT_FOUND - no queue 'api.tournament.cycle_completed.dlq' in vhost '/'` every DLQ sweep. The companion .dlq queues for the new tournament queues do not exist at runtime. Because _process_all_dlqs_once reuses one channel across all base queues, the channel-close cascades into `ChannelInvalidStateError: Channel closed by RPC timeout` for the next queues in the same sweep (api.tournament.cycle_started, api.xp.grant)."
  severity: major
  test: 1
  root_cause: "Phase 9 added the api.tournament.cycle_started/cycle_completed consumers (bot) and publisher (API outbox) but never declared those queues or their .dlq companions in infra/rabbitmq/definitions.json — unlike all 14 other queues, whose DLQs ARE declared there (grep 'tournament' in definitions.json = 0). The API publishes to the default exchange by routing-key without declaring; the bot's _set_up_queues is the only declarer. At runtime the DLQ sweep does a passive declare on api.tournament.*.dlq and gets NOT_FOUND. Secondary defect: _process_all_dlqs_once reuses ONE pooled channel for every base queue, so the channel-level NOT_FOUND closes the channel and the next queues in the same sweep fail with ChannelInvalidStateError: Channel closed by RPC timeout (observed for api.tournament.cycle_started and api.xp.grant)."
  debug_session: ""
  artifacts:
    - path: "apps/bot/extensions/rabbit.py"
      issue: "Startup declares <queue>.dlq (line ~94) but the tournament queues' DLQs are NOT_FOUND at sweep time (_process_one_dlq, line ~291, passive=True). Possible precondition mismatch on the pre-existing main queue preventing DLQ creation, or the queue was declared elsewhere (definitions.json / API publisher) without a DLQ."
    - path: "apps/bot/extensions/rabbit.py"
      issue: "_process_all_dlqs_once (line ~270) reuses a single pooled channel across every base queue; a channel-level ChannelNotFoundEntity closes the channel and poisons the rest of the sweep (cascading RPC timeout for unrelated queues)."
    - path: "infra/rabbitmq/definitions.json"
      issue: "Check whether api.tournament.cycle_started/cycle_completed (and their .dlq) are declared here, and whether the main-queue arguments match the bot's x-dead-letter-* declaration."
  missing:
    - "Ensure api.tournament.cycle_started.dlq and api.tournament.cycle_completed.dlq are declared (startup declare succeeds, or add to definitions.json)."
    - "Make the DLQ sweep resilient to a single missing/failed DLQ (per-queue channel, or passive-declare guard that skips NOT_FOUND without closing the shared channel)."
