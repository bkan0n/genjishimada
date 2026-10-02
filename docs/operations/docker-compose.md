# Docker Compose

Deploy and run Genji Shimada using Docker Compose for local development and remote environments.

## Overview

The project provides three Docker Compose configurations:

- **`docker-compose.local.yml`** - Local development (infrastructure only: PostgreSQL, MinIO)
- **`docker-compose.dev.yml`** - Remote staging server (full stack: API, bot, PostgreSQL)
- **`docker-compose.prod.yml`** - Remote production server (full stack: API, bot, PostgreSQL)

## Local Development

For local development on your Mac/Linux machine, use `docker-compose.local.yml`. This runs **infrastructure only** (PostgreSQL, MinIO) while you run the API and bot natively for fast iteration.

### Services

```yaml
services:
  postgres-local:        # PostgreSQL 17
  minio-local:           # MinIO (S3-compatible storage)
```

### Starting Local Infrastructure

```bash
docker compose -f docker-compose.local.yml up -d
```

### Ports

| Service    | Ports          | Description                    |
|------------|----------------|--------------------------------|
| PostgreSQL | 5432           | Database (host: localhost)     |
| MinIO      | 9000, 9001     | S3 API + Console               |

All services bind to `127.0.0.1` (localhost only).

### Environment Configuration

Use `.env.local` (see `.env.local.example`):

```env
APP_ENVIRONMENT=local
POSTGRES_HOST=localhost
S3_ENDPOINT_URL=http://localhost:9000
```

### Running API and Bot

Run the API and bot natively for hot reload:

```bash
# Terminal 1
just run-api

# Terminal 2
just run-bot
```

See the [Quick Start Guide](../getting-started/quickstart.md) for detailed local development instructions.

## Remote Staging (Dev Server)

The dev compose file is for deploying to a **remote staging server**, not for local development.

Both remote files (dev and prod) expect the external Docker network `genji-network` to exist.

### Services

The staging compose file defines:

```yaml
services:
  genjishimada-api-dev:      # Litestar API
  genjishimada-bot-dev:      # Discord bot
  genjishimada-db-dev:       # PostgreSQL 17
```

### Starting Staging Services

```bash
docker compose -f docker-compose.dev.yml up -d
```

To run only infrastructure services on staging:

```bash
docker compose -f docker-compose.dev.yml up -d genjishimada-db-dev
```

### Ports

| Service    | Port  | Description               |
|------------|-------|---------------------------|
| PostgreSQL | 65432 | Database (host: 127.0.0.1)|

Queue workers run inside the API and bot processes.

### Environment Variables

Required in `.env`:

```env
# PostgreSQL
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=genjishimada

# Queue worker (restricted PostgreSQL login)
QUEUE_DATABASE_URL=postgresql://genjishimada_queue_worker:REPLACE_WITH_SECRET@genjishimada-db-dev:5432/genjishimada
QUEUE_OPERATOR_IDS=141372217677053952

# API/Bot
APP_ENVIRONMENT=development
API_KEY=your_api_key_for_bot
DISCORD_TOKEN=your_discord_bot_token
```

### Verifying Services

Check service health:

```bash
docker compose -f docker-compose.dev.yml ps
```

## Production Environment

### Services

The production compose file runs:

```yaml
services:
  genjishimada-api:      # Litestar API
  genjishimada-bot:      # Discord bot
  genjishimada-db:       # PostgreSQL 17
```

### Starting Production Services

```bash
docker compose -f docker-compose.prod.yml up -d
```

### Ports

| Service    | Port  | Description               |
|------------|-------|---------------------------|
| PostgreSQL | 55432 | Database (host: 127.0.0.1)|

The API is not exposed directly; access is handled via your reverse proxy (e.g., Caddy).

### Environment Variables

Create `.env` in the repository root:

```env
# Application
APP_ENVIRONMENT=production

# Discord
DISCORD_TOKEN=your_production_bot_token

# PostgreSQL
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=secure_production_password
POSTGRES_DB=genjishimada

# Queue worker (restricted PostgreSQL login)
QUEUE_DATABASE_URL=postgresql://genjishimada_queue_worker:REPLACE_WITH_SECRET@genjishimada-db:5432/genjishimada
QUEUE_OPERATOR_IDS=141372217677053952

# API Authentication
API_KEY=secure_api_key_for_bot

# S3 Storage
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
R2_ACCOUNT_ID=your_account_id

# Email
RESEND_API_KEY=your_resend_key

# Monitoring
SENTRY_DSN=your_sentry_dsn
```

### Health Checks

The API health check is:

```yaml
healthcheck:
  test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthcheck"]
```

### Viewing Logs

**All services**:
```bash
docker compose -f docker-compose.prod.yml logs -f
```

**Specific service**:
```bash
docker compose -f docker-compose.prod.yml logs -f genjishimada-api
```

### Restarting Services

```bash
docker compose -f docker-compose.prod.yml restart genjishimada-api
```

## Networking

Both compose files attach to `genji-network`:

```yaml
networks:
  genji-network:
    external: true
```

Create it once if needed:

```bash
docker network create genji-network
```

## Volumes

The database uses a named volume for persistence.

## Next Steps

- [Infrastructure Guide](infrastructure.md) - Understand the services
- [Operations Overview](index.md) - Monitoring and backups
- [Bot Configuration](../bot/operations/configuration.md) - Configure the bot
