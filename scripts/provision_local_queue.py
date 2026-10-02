#!/usr/bin/env python3
"""Provision the queue-only login in the repository's local PostgreSQL container."""

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Set a generated local-only password without printing it or passing it as argv."""
    env_file = ROOT / ".env.local"
    if not env_file.exists():
        print("Create .env.local from .env.local.example first.", file=sys.stderr)
        return 1
    # Refuse remote Docker contexts, including contexts previously selected for deployment.
    docker_host = os.environ.get("DOCKER_HOST")
    if not docker_host:
        context = subprocess.run(["docker", "context", "inspect"], text=True, capture_output=True, check=False)
        if context.returncode:
            print("A local Docker context is required.", file=sys.stderr)
            return 1
        docker_host = json.loads(context.stdout)[0]["Endpoints"]["docker"]["Host"]
    if not docker_host.startswith(("unix://", "npipe://")):
        print("Refusing to provision credentials through a remote Docker connection.", file=sys.stderr)
        return 1
    # Fixed local container and database: this command never accepts a remote DSN.
    password = secrets.token_urlsafe(36)
    sql = f"ALTER ROLE genjishimada_queue_worker LOGIN PASSWORD '{password}';\n"
    result = subprocess.run(
        [
            "docker",
            "--host",
            docker_host,
            "compose",
            "-f",
            str(ROOT / "docker-compose.local.yml"),
            "exec",
            "-T",
            "postgres-local",
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "genji",
            "-d",
            "genjishimada",
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        print(
            "Queue login provisioning failed. Start local PostgreSQL and apply the queue migration first.",
            file=sys.stderr,
        )
        # Database output can include submitted SQL, so do not print it with credentials.
        return result.returncode
    url = f"postgresql://genjishimada_queue_worker:{quote(password)}@localhost:5432/genjishimada"
    content = env_file.read_text()
    line = f"QUEUE_DATABASE_URL={url}"
    content = (
        re.sub(r"^QUEUE_DATABASE_URL=.*$", lambda _: line, content, flags=re.MULTILINE)
        if re.search(r"^QUEUE_DATABASE_URL=", content, flags=re.MULTILINE)
        else content.rstrip() + "\n" + line + "\n"
    )
    os.chmod(env_file, 0o600)
    env_file.write_text(content)
    print("Updated the local queue-only login and .env.local. Restart a running local bot to reconnect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
