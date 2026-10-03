"""Real database migration and restricted worker permission acceptance."""

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from pgqueuer.ports.repository import EntrypointExecutionParameter
from pgqueuer.queries import Queries

from genjishimada_sdk.queue_store import enqueue_job

ROOT = Path(__file__).resolve().parents[5]
pytestmark = [pytest.mark.queue, pytest.mark.asyncio]
ROLE = "genjishimada_queue_worker"


async def test_Q15_parallel_database_migrations_share_one_restricted_role(queue_postgres):
    admin = await asyncpg.connect(queue_postgres["dsn"])
    role = f"queue_race_{uuid4().hex}"
    databases = []
    connections = []
    tasks = []
    initial = (ROOT / "apps/api/migrations/0001_init.sql").read_text()
    start = initial.index("CREATE TABLE public.jobs\n")
    end = initial.index("CREATE TABLE public.tags\n", start)
    migration = (ROOT / "apps/api/migrations/0034_postgres_queue.sql").read_text().replace(ROLE, role)
    try:
        for _ in range(2):
            database = f"queue_parallel_{uuid4().hex}"
            await admin.execute(f'CREATE DATABASE "{database}"')
            databases.append(database)
            connection = await asyncpg.connect(queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database)
            connections.append(connection)
            await connection.execute(
                "CREATE TYPE job_status AS ENUM ('queued','processing','succeeded','failed','timeout')"
            )
            await connection.execute(initial[start:end])
        pids = [connection.get_server_pid() for connection in connections]
        async with admin.transaction():
            # Both migrations must pass the absent-role check before either can
            # insert into the shared role catalog; the release forces the race.
            await admin.execute("LOCK TABLE pg_catalog.pg_authid IN SHARE MODE")
            tasks = [asyncio.create_task(connection.execute(migration)) for connection in connections]
            async with asyncio.timeout(5):
                while await admin.fetchval(
                    """SELECT count(*) FROM pg_locks WHERE relation='pg_authid'::regclass
                    AND mode='RowExclusiveLock' AND NOT granted AND pid=ANY($1::int[])""",
                    pids,
                ) != 2:
                    await asyncio.sleep(.01)
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
        for connection in connections:
            assert await connection.fetchval("SELECT to_regclass('public.pgqueuer')") is not None
            assert await connection.fetchval("SELECT has_table_privilege($1,'public.pgqueuer','SELECT')", role)
            assert not await connection.fetchval("SELECT has_table_privilege($1,'public.jobs','SELECT')", role)
        flags = await admin.fetchrow(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=$1",
            role,
        )
        assert flags is not None and not any(flags.values())
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for connection in connections:
            await connection.close()
        for database in databases:
            await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.execute(f'DROP ROLE IF EXISTS "{role}"')
        await admin.close()


@pytest.mark.parametrize("legacy", [False, True], ids=["fresh-schema", "preceding-schema-with-jobs"])
async def test_Q15_schema_preserves_legacy_jobs_and_worker_permissions(queue_postgres, legacy):
    admin = await asyncpg.connect(queue_postgres["dsn"])
    database = f"queue_schema_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    dsn = queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database
    owner = worker = None
    try:
        owner = await asyncpg.connect(dsn)
        # Apply the exact jobs DDL from the preceding schema, not a second queue schema.
        initial = (ROOT / "apps/api/migrations/0001_init.sql").read_text()
        start = initial.index("CREATE TABLE public.jobs\n")
        end = initial.index("CREATE TABLE public.tags\n", start)
        await owner.execute("CREATE TYPE job_status AS ENUM ('queued','processing','succeeded','failed','timeout')")
        await owner.execute(initial[start:end])
        await owner.execute("CREATE TABLE business_effects (id text PRIMARY KEY, value integer NOT NULL)")
        legacy_id = uuid4()
        if legacy:
            await owner.execute(
                "INSERT INTO jobs(id,action,status,error_code,error_msg,attempts) VALUES($1,'api.newsfeed.create','failed','old','retained',3)",
                legacy_id,
            )
        await owner.execute((ROOT / "apps/api/migrations/0034_postgres_queue.sql").read_text())
        if legacy:
            row = await owner.fetchrow("SELECT * FROM jobs WHERE id=$1", legacy_id)
            assert row["status"] == "failed"
            assert row["error_msg"] == "retained"
            assert row["attempts"] == 3
            assert row["queue_job_id"] is None
            assert row["event_key"] is None
        async with owner.transaction():
            response = await enqueue_job(
                owner, event_name="api.completion.submission", payload={"completion_id": 1}, event_key="role-test"
            )
        worker = await asyncpg.connect(dsn, user=ROLE)
        privileges = await worker.fetchrow(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit FROM pg_roles WHERE rolname=current_user"
        )
        assert not any(privileges.values())
        queries = Queries.from_asyncpg_connection(worker)
        entrypoints = {"api.completion.submission": EntrypointExecutionParameter(concurrency_limit=1)}
        jobs = await queries.dequeue(1, entrypoints, uuid4(), 2, timedelta(seconds=60))
        assert len(jobs) == 1
        await queries.update_heartbeat([jobs[0].id])
        await queries.retry_job(jobs[0], timedelta(), None)
        assert await owner.fetchval("SELECT status FROM pgqueuer WHERE id=$1", jobs[0].id) == "queued"
        retried = await queries.dequeue(1, entrypoints, uuid4(), 2, timedelta(seconds=60))
        assert len(retried) == 1
        await queries.log_jobs([(retried[0], "successful", None)])
        assert await owner.fetchval("SELECT count(*) FROM pgqueuer") == 0
        assert await owner.fetchval("SELECT status FROM jobs WHERE id=$1", response.id) == "succeeded"
        assert await owner.fetchval("SELECT count(*) FROM pgqueuer_log") >= 1
        for statement in [
            "SELECT * FROM public.jobs",
            "SELECT * FROM public.job_effects",
            "SELECT * FROM public.business_effects",
            "INSERT INTO public.business_effects VALUES ('forbidden',1)",
            "CREATE TABLE public.worker_created(id int)",
            "CREATE SCHEMA worker_created",
            "ALTER TABLE public.pgqueuer ADD COLUMN forbidden int",
            "SELECT public.project_queue_state()",
        ]:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await worker.execute(statement)
    finally:
        if worker is not None:
            await worker.close()
        if owner is not None:
            await owner.close()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.mark.parametrize(
    "unsafe_grant",
    [
        "GRANT SELECT ON business_effects TO PUBLIC",
        "GRANT SELECT(value) ON business_effects TO PUBLIC",
        "GRANT CREATE ON SCHEMA public TO PUBLIC",
    ],
    ids=["public-domain-read", "public-domain-column-read", "public-schema-create"],
)
async def test_Q15_upgrade_refuses_inherited_public_privileges(queue_postgres, unsafe_grant):
    admin = await asyncpg.connect(queue_postgres["dsn"])
    database = f"queue_unsafe_acl_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    dsn = queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database
    connection = None
    try:
        connection = await asyncpg.connect(dsn)
        initial = (ROOT / "apps/api/migrations/0001_init.sql").read_text()
        start = initial.index("CREATE TABLE public.jobs\n")
        end = initial.index("CREATE TABLE public.tags\n", start)
        await connection.execute(
            "CREATE TYPE job_status AS ENUM ('queued','processing','succeeded','failed','timeout')"
        )
        await connection.execute(initial[start:end])
        await connection.execute("CREATE TABLE business_effects(id text PRIMARY KEY, value integer NOT NULL)")
        await connection.execute(unsafe_grant)
        with pytest.raises(asyncpg.PostgresError, match="(?i)queue|public|role|grant|permission|privilege"):
            await connection.execute((ROOT / "apps/api/migrations/0034_postgres_queue.sql").read_text())
        # A failed upgrade must not leave a partially installed schema behind.
        assert await connection.fetchval("SELECT to_regclass('public.pgqueuer')") is None
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


async def test_Q15_upgrade_allows_table_grant_in_inaccessible_extension_schema(queue_postgres):
    admin = await asyncpg.connect(queue_postgres["dsn"])
    database = f"queue_extension_acl_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{database}"')
    dsn = queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database
    connection = worker = None
    try:
        connection = await asyncpg.connect(dsn)
        initial = (ROOT / "apps/api/migrations/0001_init.sql").read_text()
        start = initial.index("CREATE TABLE public.jobs\n")
        end = initial.index("CREATE TABLE public.tags\n", start)
        await connection.execute(
            "CREATE TYPE job_status AS ENUM ('queued','processing','succeeded','failed','timeout')"
        )
        await connection.execute(initial[start:end])
        # pg_cron grants PUBLIC table SELECT but does not grant schema USAGE.
        await connection.execute(
            "CREATE SCHEMA cron; CREATE TABLE cron.job(id integer); GRANT SELECT ON cron.job TO PUBLIC"
        )
        await connection.execute((ROOT / "apps/api/migrations/0034_postgres_queue.sql").read_text())
        assert await connection.fetchval("SELECT has_table_privilege($1,'cron.job','SELECT')", ROLE)
        assert not await connection.fetchval("SELECT has_schema_privilege($1,'cron','USAGE')", ROLE)
        worker = await asyncpg.connect(dsn, user=ROLE)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await worker.fetch("SELECT * FROM cron.job")
        assert await worker.fetchval("SELECT count(*) FROM public.pgqueuer") == 0
    finally:
        if worker is not None:
            await worker.close()
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()
