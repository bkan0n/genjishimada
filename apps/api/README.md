# API tests

Run commands from the repository root after `uv sync --all-groups --all-packages`.
Database and HTTP tests require Docker; fixtures provision PostgreSQL themselves.
Unit tests do not start or connect to PostgreSQL.

```bash
# Full suite with two workers; this is also the CI command.
just test-api

# Serial run, useful when reproducing an ordering failure.
just test-api --workers 0

# Different execution orders, without adding or removing cases.
just test-api --workers 0 --order reverse
just test-api --workers 0 --order shuffle --seed 20260928
just test-api --workers 2 --order shuffle --seed 20260928

# Existing tests selected by category, domain, or feature folder.
just test-api --workers 0 -m unit
just test-api -m database
just test-api -m integration
just test-api -m domain_maps
just test-api tests/maps

# Optional local testmon selection and optional JUnit output.
just test-api --testmon
just test-api --junitxml=/tmp/api-tests.xml
```

The runner is `scripts/run_api_tests.py`. For example:

```bash
uv run --project apps/api --group dev-api python scripts/run_api_tests.py --workers 2
```

An absolute path to the runner works from any working directory when using the
project's Python environment. Test paths and relative output paths passed to the
runner are always resolved from `apps/api`. Other arguments pass through to pytest;
use `-- --help` to inspect pytest's options. `test-api-all` and `test-api-v3` remain
aliases for the same full-suite command.

Full collection is the default. Testmon remains available for local iteration but
is never enabled by the normal command or restored from a CI cache. CI runs for
pull requests targeting any branch, including intermediate branches in a PR stack,
and for pushes to `main` or `dev`.

## Layout and isolation

Existing tests live under `tests/<feature>/`, with repository, service, and HTTP
cases alongside their feature fixtures. Shared infrastructure lives in
`tests/support/`. The `unit`, `database`, and `integration` markers distinguish
execution requirements; existing `domain_*` markers select features. Unknown
markers are errors. An integration test also uses the database marker when it
requests the database fixtures.

Each parallel worker owns one test database. Migrations and seeds run once per
worker, then the fixture captures their actual rows and sequence values. Before
each database test it clears test-created data and restores the captured baseline,
including mutable configuration and reference data. It does not preserve changes
made by a previous test. Reset operations verify that the database belongs to the
pytest fixtures.

Database connections and pools belong to function-scoped fixtures. Factories
receive a fixture-owned connection. HTTP applications use small pools, and their
lifetimes end before the next database reset. Unit tests request no database
fixtures, so importing the shared fixtures does not start infrastructure.

`create_test_app()` explicitly disables scheduled tournament and skill pollers.
The test client waits for real in-process business listeners, including skill
recomputation, before returning an HTTP response. External email and OCR emissions
are recorded without contacting those services. Dedicated poller and listener
tests can still invoke the real behavior. Test apps use a synchronous log handler
and skip repeated Sentry initialization so app construction does not accumulate
background threads. Normal `create_app()` defaults retain production logging,
Sentry, pools, listeners, and pollers.

## Diagnosing failures

The runner uses xdist's `worksteal` scheduler with two workers by default; choose a
specific count with `--workers`. Reverse and seeded shuffle reorder the entire
collection identically in every worker. Parallel scheduling still affects actual
execution order, so use `--workers 0` for an exact sequential reproduction.

Every run reports its 20 slowest setup, call, and teardown durations. Pytest dumps
thread tracebacks when an individual test phase exceeds 60 seconds. This is a
diagnostic, not a test time limit. Database lock and command timeouts and bounded
pool cleanup report resource problems near the responsible test. CI has a
20-minute job limit.

The migration inventory in `docs/testing/api-test-migration.json` tracks original
cases, parameter IDs, and skip/xfail expressions through the feature moves. From
the repository root, validate a fresh full collection with:

```bash
just test-api --workers 0 --collect-only -q > /tmp/api-collection.txt
uv run python scripts/api_test_inventory.py /tmp/api-collection.txt
```
