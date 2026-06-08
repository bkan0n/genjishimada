# Phase 07 — Deferred Items

## Pre-existing failures (not introduced by Phase 07)

- `tests/repository/tournaments/test_tournaments_repository.py::TestCheckActiveCycleForCategory::test_no_active_cycle_returns_false`
- `tests/repository/tournaments/test_tournaments_repository.py::TestCheckActiveCycleForCategory::test_active_cycle_returns_true`

**Symptom:** `check_active_cycle_for_category` returns an integer row count
instead of a boolean, so `assert result is True` fails with `assert <count> is True`.

**Status:** Confirmed pre-existing — fails in isolation on the unmodified baseline
(`assert 2 is True`) with none of the Phase 07-03 test files involved. Flagged in
the 07-03 plan `<verification>` as the known `TestCheckActiveCycleForCategory`
deferred bug. Out of scope for Wave 3 (test-only). Fix `check_active_cycle_for_category`
to coerce its result to `bool` (e.g. `return result > 0`) in a follow-up.

- `test_difficulty_exact_filter` — pre-existing `Hard +` vs `Hard` mismatch
  (noted in project MEMORY.md), unrelated to Phase 07.

## Code review findings (07-REVIEW.md, status: issues_found)

### Phase 9 prerequisite (carry forward)
- **WR-03 — Tournament RabbitMQ queues not declared.** The outbox poller publishes to
  routing keys `api.tournament.cycle_started` / `api.tournament.cycle_completed`, but no
  queue (or DLQ) with those names is declared in `infra/rabbitmq/definitions.json` /
  `infra/rabbitmq/rabbit-init.sh`. Until declared, published events drop at the default
  exchange. **This is Phase 9 scope** (Bot Queue Consumers & Announcements) — declare the
  queues + DLQs alongside the consumers. Harmless until then (no consumers exist yet, no
  cycles running), but MUST be set up in Phase 9 before tournament transitions go live.

### Pre-existing (outside Phase 07 diff — backlog)
- **CR-03 — `update_config` / `update_category` interpolate dict keys into SQL** without a
  column-name allowlist (`tournaments_repository.py`, from Phase 4). Values are parameterized;
  column names are not. Current callers pass only hardcoded fields, so not exploitable today.
  Add a `frozenset` allowlist guard in a follow-up. Not introduced by Phase 07.
- **WR-02 — LRU fallback ordering bug** in `fetch_least_recently_used_map` (Phase 5 Python) and
  faithfully mirrored by `tournaments.select_eligible_map` (D-06 parity was the requirement):
  the `LEFT JOIN cycles` without `DISTINCT ON` picks a map's *oldest* cycle row rather than its
  *most recent* use. Both sides are wrong the same way (parity test passes). Fix the Python
  source and the SQL helper together in a follow-up.

### Reviewer false positives (validated against code/tests — no action)
- CR-01 (poller/pool race): lifespan ordering sets `mq_channel_pool` before the poller starts.
- CR-02 (sleep outside try): `asyncio.sleep` is a cancellation point; shutdown is clean.
- IN-01 (`PERFORM … WHERE EXISTS`): valid PostgreSQL, matches proven `0013_coin_store.sql`;
  migration 0021 applied cleanly in tests.
- WR-04 (idempotency key): exactly one `cycle_started` + one `cycle_completed` row per cycle,
  so `tournament:{event_type}:{cycle_id}` is already unique.
