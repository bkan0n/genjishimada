---
status: resolved
trigger: "Still not getting a TOURNAMENT END notification when waiting on verification drain. The tournament end (and start of next edition) should fire immediately whether or not verification has drained; results are a SECONDARY message that appears only once verification drains. Currently no END shows until verification has fully drained."
created: 2026-06-02T00:00:00Z
updated: 2026-06-02T00:00:00Z
goal: find_and_fix
---

## Current Focus

hypothesis: CONFIRMED via live DB. bootstrap_edition writes an edition_rollover OUTBOX row
  to announce an edition's START under idempotency key tournament:rollover:{edition_id};
  when that SAME edition later ends with a verification drain, process_awaiting_results_editions
  publishes the END card (results_pending=True) under the IDENTICAL key. The bot's idempotency
  claim from the START publish silently suppresses the END publish — so the "rotation has ended"
  card never renders and the end only surfaces via the deferred results card at drain.
test: Queried live local DB (genjishimada-db-local) — processed_messages, jobs, pending_transitions, editions.
expecting: Two api.tournament.rollover publishes per drained+bootstrapped edition sharing one key; the second (END) suppressed.
next_action: RESOLVED — phase-qualified the bootstrap START key to :start so it no longer shadows the END.

## CORRECTION — original root cause (stale-claim from edition_id reuse) was FALSE

The first investigation (no live DB access) hypothesized a stale `tournament:rollover:{edition_id}`
claim from a PRIOR debug run shadowing a reused edition_id. **Live DB evidence falsified this:**

- editions are 6,7,8,9,10 — distinct, INCREMENTING serial ids. **Never reused.**
- `public.processed_messages` holds each `tournament:rollover:{N}` exactly ONCE, all claimed FRESH.
- So there was NO cross-run / cross-edition claim collision.

The real collision is **START-vs-END of the SAME edition**, both keyed `tournament:rollover:{edition_id}`.

## Symptoms

expected: |
  When a tournament edition ends, the bot should post a TOURNAMENT END notification
  ("rotation has ended / results pending") IMMEDIATELY — regardless of verification draining.
  Results are a SECONDARY, follow-up message posted once verification drains. The drain must
  NOT block the end/start announcement. Holds whether or not cycles are paused.

actual: |
  No "rotation has ended" END card appears until verification has drained — the END framing only
  surfaces via the deferred results card. The rollover-time card (from the bootstrap START row)
  renders as "A new rotation has arrived!" with no ended/pending framing, and the real END card
  is silently dropped by an idempotency-key collision.

## Evidence (live DB, 2026-06-02)

- finding: Two api.tournament.rollover jobs for edition 6, both 'succeeded'.
  detail: |
    jobs: 26d7a8bd @15:16:58 (bootstrap START row 234, drained) claimed tournament:rollover:6 FRESH.
    jobs: dd15fe05 @15:19:08 (live start-only END, results_pending=True) — the exact line the user
    pasted (10:19:08 local = 15:19:08 UTC) — finished in 30ms = idempotency-SKIPPED (claim existed),
    no card. 'succeeded' job status does NOT imply a card was posted (the skip path returns cleanly).

- finding: The bootstrap rollover row carries START framing, not END.
  file: tournaments.pending_transitions id=234
  detail: |
    payload = {"results":[], "started":[<edition 6 cycles>], "edition_id":6, "results_pending":false}.
    Bot handler (tournaments.py:378-384): has_ended = bool([]) or False = False; started non-empty
    -> title "A new rotation has arrived!"; results_pending false -> NO "Results pending…" placeholder.
    So 15:16:58 posts a START card, never an END.

- finding: bootstrap_edition is the SOLE writer of edition_rollover outbox rows.
  file: apps/api/services/tournament_service.py:508-519; migration 0025
  detail: |
    Both edition_rollover rows in the DB (ed 6 row 234, ed 7 row 236) are classified BOOTSTRAP(start)
    — created exactly at each edition's started_at. Live cron function process_edition_transitions()
    does NOT contain 'edition_rollover' (0025 rewrote it to a pure status flip). So every drained
    edition_rollover outbox row is a bootstrap START.

- finding: The edition END rollover is published DIRECTLY (not via the outbox).
  file: apps/api/services/tournament_outbox_service.py:406-411 (start-only), 431-436 (combined)
  detail: |
    process_awaiting_results_editions publishes the END (results_pending=True start-only, or combined)
    under hardcoded f"tournament:rollover:{edition_id}" — the SAME key the bootstrap START row drains
    under (_idempotency_key, was f"tournament:rollover:{edition_id}"). Collision -> bot claims START,
    skips END.

- finding: Non-drained editions render their end fine — confirms the drain-specific collision.
  detail: |
    Editions 8,9,10 (start_announced=FALSE, no drain) took the combined END path, claimed
    tournament:rollover:{N} fresh (no bootstrap row competing), and rendered. Only bootstrapped+drained
    editions (6,7) collide. Exactly matches "doesn't show an end UNTIL verification has drained."

## Eliminated

- candidate: Stale claim from edition_id reuse across debug runs (the original hypothesis).
  reason: editions are distinct incrementing serials (6..10); each rollover key claimed exactly once, fresh.
- candidate: Bot rendering logic drops the END card for results_pending=True + empty started.
  reason: tournaments.py:360 guard is False when results_pending=True; the handler builds + sends a
    valid "The rotation has ended. / Results pending verification…" card. Rendering is correct; the
    END message simply never reaches the handler (idempotency-skipped).
- candidate: transitions_paused blocks the poller / END.
  reason: process_awaiting_results_editions is not gated on transitions_paused.

## Resolution

root_cause: |
  bootstrap_edition (apps/api/services/tournament_service.py:508-519) writes an edition_rollover
  OUTBOX row to announce a bootstrapped edition's START. The outbox poller drained it under
  idempotency key tournament:rollover:{edition_id} (_idempotency_key, tournament_outbox_service.py).
  When that SAME edition later ends with a verification drain, process_awaiting_results_editions
  publishes the END card (results_pending=True) DIRECTLY under the IDENTICAL key
  tournament:rollover:{edition_id}. The bot's @queue_consumer(idempotent=True) claim from the
  bootstrap START publish makes the END publish a duplicate -> silently skipped -> no "rotation has
  ended" card. The END framing only surfaces later via the deferred edition_results card at drain.
  (Migration 0025 made bootstrap_edition the sole writer of edition_rollover outbox rows, so every
  such row is unambiguously a START.)
fix: |
  Phase-qualified the bootstrap START key. _idempotency_key (apps/api/services/tournament_outbox_service.py)
  now returns tournament:rollover:{edition_id}:start for edition_rollover outbox rows; the edition END
  rollovers keep the un-suffixed tournament:rollover:{edition_id}. Distinct keys -> no collision -> the
  END card renders at rollover time, independent of verification draining. Updated module + function
  docstrings and the 4 outbox-drain test assertions in test_outbox_poller.py to expect :start (the 6
  direct-publish END tests keep the un-suffixed key).
verification: |
  - tests/repository/tournaments/test_outbox_poller.py + tests/bot/test_tournaments_handler.py: 41 passed.
  - Broad sweep (lifecycle + sdk_events + repository/tournaments + integration): 171 passed, 1 xfailed.
  - ruff: All checks passed. basedpyright services/tournament_outbox_service.py: 0 errors.
  - NOTE: requires `just run-api` restart to take effect (API-side key change). Pre-fix editions
    already have a claimed START key; the fix applies to editions rolled over after restart.
files_changed:
  - apps/api/services/tournament_outbox_service.py (_idempotency_key :start qualifier + docstrings)
  - apps/api/tests/repository/tournaments/test_outbox_poller.py (4 outbox-drain assertions -> :start, docstring)
