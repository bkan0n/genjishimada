"""Database connection configuration for the bot's restricted queue worker."""

import os
from urllib.parse import quote


def queue_database_url() -> str:
    """Reuse the API's database location with a separate, restricted login."""
    override = os.getenv("QUEUE_DATABASE_URL")
    if override:
        return override
    password = os.getenv("QUEUE_DATABASE_PASSWORD")
    database = os.getenv("POSTGRES_DB")
    if not password or not database:
        raise ValueError("Set QUEUE_DATABASE_PASSWORD and POSTGRES_DB, or provide QUEUE_DATABASE_URL.")
    default_host = "genjishimada-db" if os.getenv("APP_ENVIRONMENT") == "production" else "genjishimada-db-dev"
    host = os.getenv("POSTGRES_HOST") or default_host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"postgresql://genjishimada_queue_worker:{quote(password, safe='')}@{host}:5432/{quote(database, safe='')}"
