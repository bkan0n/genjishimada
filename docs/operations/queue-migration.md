# PostgreSQL queue migration runbook

This runbook prepares the replacement of RabbitMQ with the PostgreSQL queue. Repository changes do not apply database migrations, change remote credentials, send messages, or delete broker data. Keep the source export and old volume until every outstanding message has an audited disposition.

The review stack is one coordinated deployment. Production deploys automatically on a push to `main`; merge the upper review layers into their parent branches first, then merge the completed foundation branch into `main`. Do not deploy an intermediate API/bot/infrastructure combination.

## Prepare

1. Run `just test-queue` and the affected feature tests (for example `just test-api tests/completions`), lint, and type checks against the candidate revision. The full existing API suite is `just test-api`; the dedicated queue runner supplies its own fixture boundary and runs faults serially. Verify local/dev/prod Compose configuration with placeholder credentials. Never exercise fault tests against deployed services.
2. Take the normal database backup. Preserve the RabbitMQ volume, configuration, queue inventory, and previous deploy revision. The broker definitions export contains topology, **not message payloads**.
3. Apply the additive queue migration as the database migration owner. The bot role is created without a password. Provision a distinct password and set the environment's `QUEUE_DATABASE_PASSWORD` secret. The bot defaults to the API's database location; `QUEUE_DATABASE_URL` remains an optional full connection override. The bot role must have no domain-table grants; do not use the API login.
4. Set `QUEUE_OPERATOR_IDS` on both API and bot, initially `141372217677053952`. Provision `jobs:manage` on the bot API key for internal job execution and recovery endpoints. The existing operator channel IDs remain unchanged.
5. Keep the old application/broker stack operational until the actual backlog inventory is available. Do not use `down -v`, volume pruning, or `--remove-orphans` as a migration shortcut.

## Check existing database privileges

Before supplying the worker credential, inspect the target database's actual permissions as the migration owner. Old or manually granted `PUBLIC` privileges can apply to a new role even with `NOINHERIT`; the fresh-schema acceptance test cannot inspect production ACLs.

```sql
SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname = 'genjishimada_queue_worker';
SELECT has_schema_privilege('genjishimada_queue_worker', 'public', 'CREATE');
SELECT parent.rolname
FROM pg_auth_members m JOIN pg_roles member ON member.oid = m.member
JOIN pg_roles parent ON parent.oid = m.roleid
WHERE member.rolname = 'genjishimada_queue_worker';
SELECT n.nspname, c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_%'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND NOT (n.nspname = 'public' AND c.relname IN ('pgqueuer', 'pgqueuer_log', 'pgqueuer_statistics', 'pgqueuer_schedules'))
  AND has_schema_privilege('genjishimada_queue_worker', n.oid, 'USAGE')
  AND (has_table_privilege('genjishimada_queue_worker', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
       OR has_any_column_privilege('genjishimada_queue_worker', c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'));
```

The role flags and schema-create check must all be false; the membership and table queries must return no rows. The table check includes column grants and requires schema access: extensions such as `pg_cron` can grant `PUBLIC` table reads while keeping their schema inaccessible. The migration refuses unsafe existing grants instead of silently changing unrelated privileges. Resolve unexpected grants before starting the worker. Check whether a grant is inherited through `PUBLIC` before changing it, since that change can affect other logins. Do not give the bot domain access as a workaround for a missing queue permission.

## Staging login setup

The API and bot use the same database, but authenticate as different roles. The bot defaults to the database's internal Docker hostname and port 5432; it does not use the host's published port 65432. Both services already join `genji-network` in Compose.

On the staging host, use a checkout of the tested stack and the existing `genjishimada-db-dev` container. After the backup and earlier migrations are complete, apply `0034` once if it has not already been applied:

```bash
docker exec -i genjishimada-db-dev sh -c 'exec psql -X -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < apps/api/migrations/0034_postgres_queue.sql
```

This creates `genjishimada_queue_worker` and grants only the queue operations it needs. It does not set a password. Open an administrator session:

```bash
docker exec -it genjishimada-db-dev sh -c 'exec psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

In that session, grant database connection access and set a new password for this login:

```text
SELECT format('GRANT CONNECT ON DATABASE %I TO genjishimada_queue_worker', current_database()) \gexec
\password genjishimada_queue_worker
```

The interactive [`\password` command](https://www.postgresql.org/docs/17/app-psql.html) keeps the cleartext password out of command history and SQL logs. Run the privilege checks above in this administrator session; do not grant the queue role membership in the API owner role or access to all tables.

In GitHub **Settings → Environments → development**, save that password as the `QUEUE_DATABASE_PASSWORD` secret. Leave `QUEUE_DATABASE_URL` absent or empty to use the shared database location. If an older URL secret is still set, it overrides the new password and location. The workflow forwards `POSTGRES_DB` and uses `genjishimada-db-dev` by default; the optional `POSTGRES_HOST` environment variable changes the host for both API and bot.

Before starting the bot, verify the restricted login over TCP using the password prompt:

```bash
docker exec -it genjishimada-db-dev sh -c 'exec psql -X -h 127.0.0.1 -W -U genjishimada_queue_worker -d "$POSTGRES_DB"'
```

Run these separately in that session:

```sql
SELECT current_user, current_database();
SELECT 1 FROM public.pgqueuer LIMIT 0;
SELECT 1 FROM core.users LIMIT 0;
SELECT 1 FROM public.jobs LIMIT 0;
```

The current user must be `genjishimada_queue_worker`, and the queue query must succeed. The final two queries must fail with permission denied. This smoke check complements the full privilege audit above; it does not replace it. The bot's existing API key also needs `jobs:manage` so its queue handlers can prepare work and request domain mutations through the API.

Once backlog reconciliation is complete, deploy the full stack to development and confirm the bot's queue supervisor connects. For production, repeat the setup against `genjishimada-db` and the **production** GitHub environment with its own password. Local development can continue using `just queue-credentials-local`, which writes a complete URL override to `.env.local`.

## Quiesce and inventory

Pause mutation traffic and every producer, including the tournament poller and scheduled producers. Drain ordinary queues with the old consumer while dependencies are healthy, then stop that consumer. Let unacknowledged deliveries return to a stable queue and record counts before exporting.

Inventory **runtime** queues and DLQs, not just the former checked-in definitions. Include `api.tournament.rollover`, `api.tournament.results`, and the retired `api.tournament.cycle_started`/`api.tournament.cycle_completed` names. Export complete message bodies and properties using broker tools that retain messages until the export is verified. Do not acknowledge/delete messages merely to inspect them. Preserve the raw export read-only with a checksum and queue counts.

Reconcile each message against current domain state, public job UUID, stored external bindings, and the old `processed_messages` claim. A pre-execution claim is ambiguous and never proves completion. Inspect already-performed effects before approving replay. Unknown or obsolete tournament payloads require an explicit decision; the importer does not guess a conversion.

## Reviewable import manifest

Create a JSON Lines manifest from the retained export. Each nonempty line represents one source message. Give it a stable `source_id` (export identity plus queue/message identity), the original `queue`, decoded JSON `payload`, optional original public `job_id`, and a reviewed disposition. Preserve the original raw export separately; omit credentials/authorization headers from the review manifest.

Supported dispositions:

| Input disposition | Result |
| --- | --- |
| `enqueue` with nonempty `evidence` and `effects_started: false` | Validate a supported payload and enqueue work confirmed never to have started. Prior claims or completed effects keep it in reconciliation. |
| `completed` with `evidence` | Record the evidence of completed work without enqueueing. |
| `discarded` with `evidence` | Record the explicit decision and reason without enqueueing. |
| Missing, unsupported, malformed, or ambiguous | Preserve as `needs_reconciliation`; do not execute. |

An example using illustrative IDs:

```json
{"source_id":"export-2026-10-02:api.newsfeed.create:42","queue":"api.newsfeed.create","payload":{"newsfeed_id":42},"event_key":"legacy-newsfeed:42","disposition":"enqueue","effects_started":false,"evidence":"Reviewed source, domain row, and destinations; no effect was attempted."}
```

The exact payload must match its shared SDK event model; the example is not production data. Supply the original `job_id` when it can be identified. Use the same `event_key` for duplicate copies of the same business event; different legitimate transitions need different keys.

Only explicitly unstarted work can be imported for execution. Missing or non-boolean `effects_started`, a truthy `legacy_claim`, or nonempty `completed_effects` keeps a record in `needs_reconciliation`, even if `effects_reconciled: true` is supplied. This importer does not reconstruct effect receipts or external bindings. Partially executed work must remain preserved until its completed effects can be retained through an explicit, event-specific recovery; restarting its full handler could send duplicate messages or award XP twice.

Copies sharing a public job UUID or event name/key are reviewed together before any enqueue. If one copy is unresolved, completed, or discarded, conflicting enqueue requests for that logical work also remain in reconciliation, regardless of source order. Apply includes previously recorded dispositions and stored job history in this check. Prepare the complete manifest before resuming workers; an unstarted assertion on a duplicate cannot override known prior execution.

Run the default dry-run without any database connection:

```bash
uv run --project apps/api python scripts/import_queue_backlog.py /path/to/reviewed-manifest.jsonl
```

Review the disposition counts, then use the migration-owner connection through a secret environment variable for the explicit apply:

```bash
uv run --project apps/api python scripts/import_queue_backlog.py /path/to/reviewed-manifest.jsonl --apply
```

`--apply` reads `QUEUE_IMPORT_DATABASE_URL` by default; `--dsn-env` selects another environment variable. Never put a live password in a command argument, checked-in file, or report. The importer writes `public.job_imports` and accepted queue work in one transaction. Apply also locks any original public job: execution history (including attempts, start/finish timestamps, or a processing/failed state) overrides an unstarted assertion and holds the record without altering that job. Dry-run only checks the manifest, so apply may report additional reconciliation items. Rerunning the same manifest does not create another job. Reusing a `source_id` with changed content fails the transaction, so a later reconciliation must be an explicit audited operation rather than silently editing an already-imported disposition. Malformed lines are retained with a generated export/line identity.

Confirm every source line has a disposition, count the source messages and imported records, inspect all `needs_reconciliation` items, and check that no job lost its completed-effect evidence. Keep unresolved items preserved; do not treat a successful importer exit as proof they were completed.

## Start and retire

Start the migrated API and bot with the prepared credentials, confirm their workers connect, then resume mutation traffic. The existing job UUID/status contracts and community wording remain unchanged. Persistent retries and operator controls use the same logical jobs and completed effects.

Once the backlog and new workers are reconciled, stop/remove only the old broker container to release its RAM. Retain its named volume and exports. Deleting that volume is a separate, explicit cleanup action after verification.

Review broker-specific resources outside this repository: Caddy routes for `rabbitmq.genji.pk` and `dev-rabbitmq.genji.pk`, their Cloudflare records, Keycloak `rabbitmq-prod`/`rabbitmq-dev` clients, broker roles/groups/audience mappers, management OAuth credentials, and RabbitMQ GitHub/environment secrets. Remove only resources confirmed to belong exclusively to the retired broker. Shared Keycloak, proxy, networking, and monitoring remain needed. None of these remote changes is performed by this code change.

## Ongoing recovery

Use the [operator CLI](../services/queue.md#operator-command-line) to inspect current state, see queue counts, retry a diagnosed failure, reconcile an uncertain result, or record a discard. These commands require the API and use its authorization/audit service; they do not bypass recovery checks through direct database updates.

The API retains compact job summaries and effect evidence while pruning old successful-job logs after 30 days. Held or uncertain work remains available for recovery. Database maintenance is automatic and does not remove preserved broker exports or volumes.

## Rollback boundary

Before the new workers execute work, the old revision and preserved broker data remain available for a coordinated rollback. After either system has executed new work, stop producers/workers and reconcile effect receipts, queued rows, and the export before choosing which work to resume. Do not run old and new consumers against duplicate logical work or restore an old database over newly accepted submissions.
