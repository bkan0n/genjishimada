# Database Service

PostgreSQL stores the persistent data used by the API, bot, and website.

## Purpose

This database stores user data, map metadata, run results, and other records shared across services.

## Compose configuration

The database is defined in:

- `docker-compose.local.yml` as `postgres-local` (for local development)
- `docker-compose.dev.yml` as `genjishimada-db-dev` (for remote staging)
- `docker-compose.prod.yml` as `genjishimada-db` (for remote production)

### Local Development

- Uses the `postgres:17` image
- Exposes port `5432` on `127.0.0.1`
- Includes health checks via `pg_isready`
- Simple credentials (genji/local_dev_password)

### Remote Staging

- Uses the `postgres:17` image
- Exposes port `65432` on `127.0.0.1`
- Includes health checks via `pg_isready`

### Remote Production

- Uses the `postgres:17` image
- Exposes port `55432` on `127.0.0.1`
- Includes health checks via `pg_isready`

## Environment variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_USER` | Username for the database |
| `POSTGRES_PASSWORD` | Password for the database |
| `POSTGRES_DB` | Name of the primary database |

## Local development

1. Start local infrastructure:
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

2. Connect to the database:
   - Host: `localhost`
   - Port: `5432`
   - User: `genji`
   - Password: `local_dev_password`
   - Database: `genjishimada`

3. Or use the container directly:
   ```bash
   docker exec -it genjishimada-db-local psql -U genji -d genjishimada
   ```

See the [Quick Start Guide](../getting-started/quickstart.md) for full local development setup.
