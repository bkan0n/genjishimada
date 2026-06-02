---
phase: 09-bot-queue-consumers-announcements
reviewed: 2026-05-30T18:00:09Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - apps/bot/extensions/rabbit.py
  - infra/rabbitmq/definitions.json
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 09: Code Review Report (GAP-CLOSURE)

**Reviewed:** 2026-05-30T18:00:09Z
**Depth:** standard
**Scope:** GAP-CLOSURE — only the phase 09-03 changes at base `4c31fa4^`:
- Tournament queue + DLQ declarations in `infra/rabbitmq/definitions.json`
- DLQ-sweep hardening in `apps/bot/extensions/rabbit.py` (`_process_all_dlqs_once` per-base-queue channel isolation + `_process_one_dlq` `ChannelNotFoundEntity` guard)
**Status:** issues_found

## Summary

The diff is small and the core intent is sound. The two new tournament queue/DLQ
pairs (`api.tournament.cycle_started[.dlq]`, `api.tournament.cycle_completed[.dlq]`)
are correctly modeled on the existing `api.xp.grant` canonical pair, the JSON parses
cleanly, the routing keys match, and the queue names line up exactly with the bot
consumers in `apps/bot/extensions/tournaments.py` and the API outbox routing in
`apps/api/services/tournament_outbox_service.py`. The vhost `default_queue_type:
classic` reconciles the bot's runtime declare (which omits `x-queue-type`) with the
definitions' explicit `x-queue-type: classic`, so no `PRECONDITION_FAILED` is
introduced. All consumer-registered queues now have a matching `.dlq` in
definitions.json (cross-checked all 17 consumer queues + the 2 new tournament queues),
so the new guard does not paper over a current gap.

The per-base-queue channel isolation in `_process_all_dlqs_once` is a real and correct
fix: a channel-level `NOT_FOUND` previously closed the shared channel and poisoned the
rest of the sweep. Moving `acquire()` inside the loop is the right shape.

Two issues are worth flagging: the `ChannelNotFoundEntity` guard silently and
permanently swallows a genuine missing-DLQ misconfiguration (not just a startup race)
at `info` level, and `_process_one_dlq` now passively declares the same DLQ twice in
immediate succession (dead/redundant work, plus a TOCTOU path that escapes the guard).

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `ChannelNotFoundEntity` guard permanently masks a missing-DLQ misconfiguration

**File:** `apps/bot/extensions/rabbit.py:300-304`
**Issue:** The new guard catches `ChannelNotFoundEntity`, logs at `log.info` with the
phrasing "does not exist yet; skipping," and returns `0`. The comment frames this as a
transient gap "until definitions.json carries every .dlq," but the bot's own
`_set_up_queues` already declares `<queue>.dlq` at startup (line 95) for every
registered handler. In steady state a missing DLQ is therefore NOT a transient race —
it indicates a queue that is being swept but was never declared (a handler registered
after the startup declare loop, or a definitions/runtime divergence on a fresh broker).
The current behavior downgrades that to a quiet, indefinitely-repeating `info` line
every `DLQ_PROCESS_INTERVAL` (60s) with no escalation and no self-correction, so a real
misconfiguration is invisible in normal log triage. The "yet" wording will also age
poorly once readers assume the condition is benign.
**Fix:** Either log at `warning` so the condition surfaces in triage, and/or declare the
DLQ instead of skipping so the sweep self-heals the same way `_set_up_queues` does:
```python
try:
    dlq = await channel.declare_queue(dlq_name, passive=True)
except ChannelNotFoundEntity:
    # Self-heal: a registered queue should always have a DLQ.
    log.warning("[!] [DLQ] %s missing; declaring it now.", dlq_name)
    dlq = await channel.declare_queue(dlq_name, durable=True)
```
At minimum, change `log.info` to `log.warning` and drop "yet".

### WR-02: `_process_one_dlq` passively declares the same DLQ twice (redundant + TOCTOU escapes the guard)

**File:** `apps/bot/extensions/rabbit.py:301, 312`
**Issue:** Line 301 does `dlq = await channel.declare_queue(dlq_name, passive=True)`
(now wrapped in the try/except) to read `message_count`; line 312 then does
`queue = await channel.declare_queue(dlq_name, passive=True)` again — an identical
passive declare against the same channel/queue. This is a redundant broker round-trip on
every non-empty DLQ on every sweep tick. More importantly, the second declare on line
312 is NOT inside the `ChannelNotFoundEntity` guard: if the queue is deleted between
line 301 and line 312 (TOCTOU), the second declare raises `ChannelNotFoundEntity`
uncaught here. It is still contained by the per-queue `except Exception` in
`_process_all_dlqs_once` (so it won't poison the sweep), but it logs a full exception
traceback instead of the intended quiet skip — defeating the purpose of the new guard.
**Fix:** Reuse the already-declared `dlq` handle instead of re-declaring:
```python
initial_count = dlq.declaration_result.message_count or 0
cap = min(initial_count, DLQ_MAX_PER_QUEUE_TICK)
if cap == 0:
    log.debug("[DLQ] %s is empty.", dlq_name)
    return 0

processed = 0
queue = dlq  # reuse; drop the second passive declare on line 312
```

## Info

### IN-01: `nack(requeue=True)` for already-notified messages burns the per-tick cap

**File:** `apps/bot/extensions/rabbit.py:320-324`
**Issue:** When a DLQ message already carries `DLQ_HEADER_KEY`, it is
`nack(requeue=True)`-ed and `processed` is incremented. The requeued message returns to
the head of the queue and, with `prefetch_count=100`, may be re-fetched within the same
sweep, nacked again, and consume another unit of `cap`. The loop is correctly bounded by
`cap = min(initial_count, DLQ_MAX_PER_QUEUE_TICK)` so this cannot spin forever, but on a
DLQ composed mostly of already-notified messages the sweep can exhaust its budget
re-circulating the same handful of messages without making forward progress on new ones.
Correctness-safe (no infinite loop, no data loss) but wastes the tick budget. Adjacent
to the changed code rather than introduced by it.
**Fix:** Count only newly-alerted republishes toward `cap`, or break once a full pass
yields only already-notified messages.

### IN-02: Channel-isolation comment overstates the guarantee

**File:** `apps/bot/extensions/rabbit.py:271-275, 296-299`
**Issue:** The comment states per-queue channel isolation "means one failing DLQ cannot
cascade into the rest of the sweep." That holds for channel-level errors raised inside
`_process_one_dlq`, but the second passive declare on line 312 (see WR-02) and the
guild-missing `RuntimeError` on line 328 both escape `_process_one_dlq` and are
contained only by the outer `except Exception` in `_process_all_dlqs_once` — not by
channel scoping alone. The comment reads as if channel-per-queue acquisition is the sole
mechanism.
**Fix:** No code change required; optionally tighten the comment to credit the outer
`except Exception` as the containment boundary.

---

_Reviewed: 2026-05-30T18:00:09Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
