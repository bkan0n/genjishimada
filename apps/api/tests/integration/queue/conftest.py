"""Isolated PostgreSQL infrastructure for backend queue acceptance tests."""

from __future__ import annotations

import asyncio
import subprocess
import socket
import sys
import time
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "libs/sdk/src"))


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """This suite owns its database; never alter the application's shared fixture."""
    yield


@pytest.fixture(scope="session")
def queue_postgres():
    name = f"genji-queue-acceptance-{uuid4().hex[:12]}"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        host_port = listener.getsockname()[1]
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-p",
            f"127.0.0.1:{host_port}:5432",
            "postgres:17",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        port = subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True).strip().rsplit(":", 1)[1]
        for _ in range(100):
            result = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True
            )
            if result.returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Isolated PostgreSQL did not become ready")
        yield {"name": name, "dsn": f"postgresql://postgres@127.0.0.1:{port}/postgres"}
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)


@pytest.fixture
async def queue_dsn(queue_postgres):
    database = f"queue_{uuid4().hex}"
    admin = await asyncpg.connect(queue_postgres["dsn"])
    await admin.execute(f'CREATE DATABASE "{database}"')
    dsn = queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("""
            CREATE TYPE job_status AS ENUM ('queued','processing','succeeded','failed','timeout');
            CREATE TABLE public.jobs (id uuid PRIMARY KEY, action text NOT NULL,
                status job_status NOT NULL DEFAULT 'queued', error_code text, error_msg text,
                attempts int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(),
                started_at timestamptz, finished_at timestamptz);
            CREATE TABLE business_effects (id text PRIMARY KEY, value integer NOT NULL);
        """)
        migration = ROOT / "apps/api/migrations/0034_postgres_queue.sql"
        if migration.exists():
            await conn.execute(migration.read_text())
    finally:
        await conn.close()
    try:
        yield dsn
    finally:
        if admin.is_closed():
            admin = await asyncpg.connect(queue_postgres["dsn"])
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def queue_db(queue_dsn):
    conn = await asyncpg.connect(queue_dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def eventually(check, *, timeout=8):
    async with asyncio.timeout(timeout):
        while True:
            value = await check()
            if value:
                return value
            await asyncio.sleep(0.025)
