# Database Service

PostgreSQL stores the persistent data used by the API, bot, and website.

## Purpose

This database stores user data, map metadata, run results, and other records shared across services.

## Compose configuration

The database is defined in:

- `docker-compose.dev.yml` as `genjishimada-db-dev`
- `docker-compose.prod.yml` as `genjishimada-db`

### Development

- Uses the `postgres:17` image
- Exposes port `65432` on the host
- Includes health checks via `pg_isready`

### Production

- Uses the `postgres:17` image
- Exposes port `55432` on the host
- Includes health checks via `pg_isready`

## Environment variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_USER` | Username for the database |
| `POSTGRES_PASSWORD` | Password for the database |
| `POSTGRES_DB` | Name of the primary database |

## Local development

1. Create a `.env` file with `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.
2. Start the service:
   ```bash
   docker compose -f docker-compose.dev.yml up -d genjishimada-db-dev
   ```
3. Connect using:
   - Host: `localhost`
   - Port: `65432`
   - User: value of `POSTGRES_USER`
   - Password: value of `POSTGRES_PASSWORD`
   - Database: value of `POSTGRES_DB`
