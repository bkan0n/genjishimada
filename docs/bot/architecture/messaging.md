# Messaging and queues

The bot processes durable jobs stored by PGQueuer 1.1.1 in PostgreSQL. Queue handlers live alongside their feature modules and use the shared `queue_consumer` decorator. The API owns business data and enqueues jobs in the same transaction as the change that requires them.

## Worker lifecycle

The queue supervisor starts after extensions register handlers. It uses the API's database location with the separate `genjishimada_queue_worker` login and `QUEUE_DATABASE_PASSWORD`; `QUEUE_DATABASE_URL` can override that connection. Its handlers receive a decoded SDK event and transport-neutral `JobContext`; they call the API for domain reads and writes. Persistent views restore independently of any backlog.

The worker stops accepting work on shutdown, allows handlers to finish, and leaves unfinished work recoverable if draining times out. PostgreSQL and API outages cause bounded reconnect delays without exhausting the ordinary handler failure budget. Claims are fenced so an old process cannot complete a job now owned by another worker.

## Event ownership

The shared SDK registry defines all supported event names and payloads. The bot owns 21 existing `api.*` events for completions, map edits, newsfeed, notifications, playtests, tournaments, and XP. The API owns the `completion.ocr.requested`, `tournament.ocr.requested`, and `map.linked.newsfeed.requested` continuations.

To add an event, register its payload and owner, add the matching worker handler, and enqueue through the business transaction. Contract tests must cover the new producer and consumer together.

## Replay and effects

A durable `(action, event_key)` identifies the business operation. Reusing a key with different payload content is an error. Distinct legitimate transitions, such as verify → reject → verify, use different persisted transition identities.

A claimed job may execute more than once. A handler must record additive mutations and their receipts atomically through the API, and bind external sends to their destination and effect key. Completed effects are reused on retry. If a send might have succeeded but its result was not saved, the effect remains uncertain until reconciled; blindly replaying it can duplicate a message.

## Failure recovery

After the ordinary retry budget is exhausted, the job remains held with its payload, failure generation, and diagnostic state. The alert supervisor independently reads failure state through the API and posts to the configured operator channel. Persistent **Retry job** and **Details** controls survive bot restarts.

Retries go through the API's authorized recovery service and preserve the logical job and completed effects. Stale controls, concurrent retries, successful jobs, and unresolved external effects cannot trigger a second execution incorrectly. See [Queue operations](../../services/queue.md).

## Verification

`just test-queue` runs backend acceptance against real PostgreSQL, including process death, stale claims, database restart, atomic enqueue, effect replay, and retry authorization. `just test-queue-fast` omits fault injection. External effects use a transport-independent recorder; this suite does not test Discord components or connect to Discord.
