---
status: partial
phase: 09-bot-queue-consumers-announcements
source: [09-VERIFICATION.md]
started: 2026-05-30T18:09:59Z
updated: 2026-05-31T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. New-cycle announcement embed — live render
expected: When a `api.tournament.cycle_started` event fires, the bot posts an embed in the configured tournament announcements channel showing map name, difficulty, category name, a clickable workshop-code link, the cycle end time, and the map banner as a thumbnail.
result: [pending]

### 2. Results embed + champion role transfer — end-to-end
expected: When a `api.tournament.cycle_completed` event fires with a winner, the bot posts ONE results embed (Top-3 podium, winner @mention, "crowned Champion" line, NO XP line), and the category champion Discord role is stripped from all prior holders and granted to the winner. Role op ordering is transfer-first, single send-last.
result: [pending]

### 3. Vacant cycle (no winner)
expected: When a cycle completes with `winner_user_id = None`, the champion role is stripped from all current holders and left vacant (granted to no one); the results embed still posts with "No submissions"/empty podium handling.
result: [pending]

### 4. Duplicate-event de-duplication
expected: Redelivery of the same cycle event (same `message_id = tournament:{event_type}:{cycle_id}`) does NOT produce a duplicate announcement or a second role transfer — the idempotency claim short-circuits the handler.
result: [pending]

### 5. Broker reload — tournament queues exist + silent DLQ sweep (09-03 gap closure)
expected: After rebuilding/restarting the RabbitMQ broker (`docker compose -f docker-compose.local.yml up -d --build rabbitmq`) so it reloads `definitions.json`, then restarting the bot, observe one full DLQ sweep interval (~60s). No `ChannelNotFoundEntity` / "Channel closed by RPC timeout" log lines appear for `api.tournament.cycle_started`, `api.tournament.cycle_completed`, or `api.xp.grant`. The four tournament queues (+ `.dlq`) exist at broker boot.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
