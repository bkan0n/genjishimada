# Background queue

PGQueuer 1.1.1 stores background work in the existing PostgreSQL database. Workers run inside the API and bot processes. A business change, its public job UUID, and its queue row commit together, so accepted work remains available after services restart.

Jobs sharing an entity key run in enqueue sequence. Before checking for earlier unfinished work, a worker waits for pending enqueue transactions for that entity to finish. Unrelated entities can continue. Legacy jobs receive their sequence when first imported into the PostgreSQL queue; their public UUID and that sequence remain stable on retries.

## Credentials and startup

Apply the checked-in queue migration with the database migration owner before starting the new workers. Runtime worker credentials do not install or upgrade schema.

- The API uses its existing database connection for transactional enqueue and its API-owned worker.
- The bot uses `QUEUE_DATABASE_URL`, authenticating as `genjishimada_queue_worker`. This role can consume and maintain queue records but cannot read or mutate domain tables, create schema, or administer the database.
- `QUEUE_OPERATOR_IDS` is a comma-separated operator allowlist, initially `141372217677053952`. Configure the same value for API and bot; the API enforces authorization.
- The authenticated bot API key needs `jobs:manage` for internal job execution and recovery endpoints.

For local development, copy `.env.local.example` to `.env.local`, start `just infra-up`, and apply the migrations. Then run:

```bash
just queue-credentials-local
```

The command targets only `postgres-local` in the local Compose file. It generates a random worker password, supplies it through standard input, and saves the queue URL to `.env.local` with owner-only permissions. It refuses remote Docker contexts and never prints the password. Restart a running local bot after rotating the login.

For deployment, provision a distinct password through your normal database administration process and store the URL in the environment's `QUEUE_DATABASE_URL` secret. Use the relevant PostgreSQL service name (`genjishimada-db-dev` or `genjishimada-db`) as the host. Do not reuse the API database owner. Both deployed application containers have a 45-second stop grace period.

## Inspecting and retrying work

Existing `/api/v3/internal/jobs/{uuid}` responses retain their public UUID/status contract. A pending retry is `queued`, a claimed job is `processing`, a completed job is `succeeded`, and a held/discarded job is `failed`.

Terminal failures appear in the existing operator Discord channel and retain the existing recipient. **Details** shows current diagnostic state; **Retry job** invokes the same authenticated API recovery service used by operational tools. The controls survive restarts. Automatic retry attempts do not create new logical jobs or a new alert on every poll.

After diagnosing and fixing a failure, retry the existing job. A retry increments its generation, resets the ordinary failure budget, and retains event identity, payload, public UUID, completed effect receipts, and message bindings. Duplicate requests resolve the existing audited action. Old controls cannot act on a later failure generation. The original alert updates as work progresses.

An uncertain external effect requires a recorded reconciliation decision before retry. Inspect the actual result and record whether it completed or can safely run again. A failed job must not be treated as evidence that every earlier step failed.

## Operator command line

`scripts/queue_jobs.py` uses the same authenticated API recovery routes as the operator controls. Set `QUEUE_API_URL` to the API origin (for example `http://localhost:8000` locally), provide `API_KEY` through your secret environment, and set `QUEUE_OPERATOR_ID` to your allowlisted Discord user ID. Remote access should use the HTTPS API origin. The key needs `jobs:manage`; the API validates the operator for every command. Credentials never appear in command arguments.

```bash
uv run --project apps/api python scripts/queue_jobs.py stats
uv run --project apps/api python scripts/queue_jobs.py list --status failed
uv run --project apps/api python scripts/queue_jobs.py inspect "$JOB_ID"
uv run --project apps/api python scripts/queue_jobs.py retry "$JOB_ID" --generation 0 --request-id diagnose-and-retry-001
```

Set `JOB_ID` to the job being investigated and use its actual `retry_generation` from inspection. A mutating command prints its request ID before contacting the API. If the response is lost, inspect the job and reuse that same request ID, generation, and arguments when repeating the request. The client never automatically retries a mutation or fetches a newer generation to override a stale decision.

Reconcile an uncertain effect by supplying evidence of its completed result as a JSON object, or by explicitly permitting a repeat after checking the destination:

```bash
uv run --project apps/api python scripts/queue_jobs.py reconcile "$JOB_ID" "$EFFECT_KEY" --generation 0 --result-file /path/to/completed-result.json --reason "Confirmed existing delivery" --request-id reconcile-001
uv run --project apps/api python scripts/queue_jobs.py reconcile "$JOB_ID" "$EFFECT_KEY" --generation 0 --resend --reason "Confirmed no delivery exists" --request-id reconcile-002
uv run --project apps/api python scripts/queue_jobs.py discard "$JOB_ID" --generation 0 --reason "Source operation was canceled" --request-id discard-001
```

All recovery commands require the inspected generation so an older diagnosis cannot change a newer failure. Reconciliation does not retry the whole job; inspect the result and then request retry when appropriate. A completed-result object must describe the actual effect's known result, such as its message binding; do not invent a success record.

`stats` returns ready, delayed, processing, and held counts, oldest ready age in seconds, and the number of uncertain effects. `list` defaults to actionable work and accepts `--limit` from 1 to 100.

## Retention

The API runs queue-log maintenance hourly in batches of at most 1,000 successful jobs. It uses PostgreSQL's clock for the 30-day cutoff, verifies the latest terminal record, and persists the final summary in the same transaction that removes old detailed logs. Jobs with an active queue row, a held/retrying/dependency-blocked status, or an uncertain effect are preserved. Public UUIDs, event identities, effect receipts, operational actions, alert bindings, and import evidence are retained.

## Verification

```bash
just test-queue       # All Q01–Q28 backend acceptance groups, including fault injection
just test-queue-fast  # Excludes isolated process/container failure cases
```

A running Docker engine and repository dependencies are sufficient. The suite owns disposable PostgreSQL instances, uses a transport-independent effect recorder, and does not require production credentials or contact Discord, Sentry, or OCR services. The full run is mandatory in CI, disables testmon selection, and runs serially. Empty collection, skipped/xfail required scenarios, or missing acceptance IDs fail the run. Results and sanitized worker logs are written under `artifacts/queue/`.

Queue tests remain under `apps/api/tests/integration/queue/` with an independent fixture boundary. Run the existing feature-organized API tests separately with `just test-api`; add a feature path such as `tests/completions` to narrow that suite. The ordinary API runner defaults to two workers and supports `--workers 0` for serial diagnosis.

See [Migration runbook](../operations/queue-migration.md) for backlog reconciliation and deployment preparation. Updating the repository does not deploy the migration or delete old service data.
