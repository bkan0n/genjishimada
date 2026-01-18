# Docker Compose

Deploy Genji Shimada using Docker Compose for development and production environments.

## Overview

The project provides two Docker Compose configurations:

- **`docker-compose.dev.yml`** - Development stack (API, bot, Postgres, RabbitMQ)
- **`docker-compose.prod.yml`** - Production stack (API, bot, Postgres, RabbitMQ)

Both files expect the external Docker network `genji-network` to exist.

## Development Environment

### Services

The development compose file defines:

```yaml
services:
  genjishimada-api-dev:      # Litestar API
  genjishimada-bot-dev:      # Discord bot
  genjishimada-db-dev:       # PostgreSQL 17
  genjishimada-rabbitmq-dev: # RabbitMQ
```

### Starting Development Services

```bash
docker compose -f docker-compose.dev.yml up -d
```

To run only infrastructure services:

```bash
docker compose -f docker-compose.dev.yml up -d \
  genjishimada-db-dev \
  genjishimada-rabbitmq-dev
```

### Ports

| Service    | Port  | Description               |
|------------|-------|---------------------------|
| PostgreSQL | 65432 | Database (host: 127.0.0.1)|

RabbitMQ management UI is not exposed directly in this repo.

### Environment Variables

Required in `.env`:

```env
# PostgreSQL
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=genjishimada

# RabbitMQ
RABBITMQ_USER=admin
RABBITMQ_PASS=dev_password

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
  genjishimada-rabbitmq: # RabbitMQ
```

### Starting Production Services

```bash
docker compose -f docker-compose.prod.yml up -d
```

### Ports

| Service    | Port  | Description               |
|------------|-------|---------------------------|
| PostgreSQL | 55432 | Database (host: 127.0.0.1)|

The API and RabbitMQ are not exposed directly; access is handled via your reverse proxy (e.g., Caddy).

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

# RabbitMQ
RABBITMQ_USER=admin
RABBITMQ_PASS=secure_production_password

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

The database and RabbitMQ use named volumes for persistence.

## Next Steps

- [Infrastructure Guide](infrastructure.md) - Understand the services
- [Operations Overview](index.md) - Monitoring and backups
- [Bot Configuration](../bot/operations/configuration.md) - Configure the bot
