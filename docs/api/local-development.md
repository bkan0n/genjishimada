# Local Development

This guide explains how to run the API and bot locally for fast development iteration.

## Overview

The recommended local development setup:

- **Infrastructure** (PostgreSQL, RabbitMQ, MinIO) runs in Docker containers
- **API and bot** run natively on your machine for fast iteration and hot reload
- **Database** can be imported from dev/prod VPS for real data
- **MinIO** provides S3-compatible storage locally (ephemeral, no persistence needed)

## Prerequisites

- Docker and Docker Compose
- Python 3.13+
- `uv` and `just` installed
- SSH access to VPS (for database imports)

## Quick Start

### 1. Install Dependencies

```bash
just setup
```

### 2. Configure Environment

Copy the local environment template:

```bash
cp .env.local.example .env.local
```

Edit `.env.local` and set your Discord bot token:

```env
DISCORD_TOKEN=your_dev_bot_token_here
DISCORD_GUILD_ID=your_test_guild_id_here
```

All other settings are pre-configured for local development.

### 3. Start Infrastructure Services

Start PostgreSQL, RabbitMQ, and MinIO:

```bash
docker compose -f docker-compose.local.yml up -d
```

Verify all services are healthy:

```bash
docker compose -f docker-compose.local.yml ps
```

Expected output:
```
NAME                        STATUS
genjishimada-db-local       Up (healthy)
genjishimada-minio-local    Up (healthy)
genjishimada-rabbitmq-local Up (healthy)
```

### 4. Create MinIO Bucket

First-time setup only:

```bash
# Install MinIO client (if not already installed)
brew install minio/stable/mc  # macOS
# or visit https://min.io/docs/minio/linux/reference/minio-mc.html

# Configure MinIO client
mc alias set local http://localhost:9000 genji local_dev_password

# Create bucket for images
mc mb local/genji-parkour-images
```

### 5. Import Database (Optional)

To work with real data from dev or production:

```bash
# Import from development environment
./scripts/import-db-from-vps.sh dev

# Or from production (use with caution)
./scripts/import-db-from-vps.sh prod
```

**Requirements**:
- SSH access to the VPS
- SSH config entry named `genji-vps` in `~/.ssh/config`

The script will:
1. Connect to VPS via SSH
2. Dump the selected database
3. Drop your local database
4. Recreate it with the imported data

### 6. Run API and Bot

In separate terminal windows:

```bash
# Terminal 1: Run API
just run-api

# Terminal 2: Run Bot
just run-bot
```

The API starts at **http://localhost:8000**.

## Accessing Services

### API

- **Endpoint**: http://localhost:8000
- **Health Check**: http://localhost:8000/healthcheck
- **API Docs**: http://localhost:8000/schema (Swagger UI)

### RabbitMQ Management

- **URL**: http://localhost:15672
- **Username**: `genji`
- **Password**: `local_dev_password`

### MinIO Console

- **URL**: http://localhost:9001
- **Username**: `genji`
- **Password**: `local_dev_password`

### PostgreSQL

Connect directly using any PostgreSQL client:

```bash
psql postgresql://genji:local_dev_password@localhost:5432/genjishimada
```

Or using Docker:

```bash
docker exec -it genjishimada-db-local psql -U genji -d genjishimada
```

## Development Workflow

### Making Changes

1. Edit code in `apps/api/` or `apps/bot/`
2. Changes are automatically reloaded (API uses Litestar's auto-reload, bot uses hot reload)
3. Test your changes

### Running Tests

```bash
# Run all tests
just test-all

# Run API tests only
just test-api

# Run specific test file
uv run --project apps/api pytest apps/api/tests/test_maps.py -v
```

### Linting and Type Checking

```bash
# Lint everything
just lint-all

# Lint API only
just lint-api

# Lint bot only
just lint-bot
```

### Database Changes

If you need to test database migrations:

1. Write your migration SQL in `apps/api/migrations/`
2. Apply it to local database:
   ```bash
   docker exec -i genjishimada-db-local psql -U genji -d genjishimada < apps/api/migrations/0004_your_migration.sql
   ```

### Refreshing Data

To get latest data from VPS:

```bash
./scripts/import-db-from-vps.sh dev
```

## Environment Configuration

### Local vs VPS Environments

The application uses environment variables to detect where it's running:

**Local development** (`.env.local`):
```env
APP_ENVIRONMENT=local
POSTGRES_HOST=localhost
RABBITMQ_HOST=localhost
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET_NAME=genji-parkour-images
S3_PUBLIC_URL=http://localhost:9000/genji-parkour-images
```

**VPS deployment** (automatic via Docker):
```env
APP_ENVIRONMENT=development  # or production
POSTGRES_HOST=genjishimada-db-dev  # container name
RABBITMQ_HOST=genjishimada-rabbitmq-dev  # container name
# S3_ENDPOINT_URL not set (uses R2)
```

### Key Environment Variables

| Variable | Local Value | VPS Value | Description |
|----------|-------------|-----------|-------------|
| `APP_ENVIRONMENT` | `local` | `development`/`production` | Environment identifier |
| `POSTGRES_HOST` | `localhost` | Container name | Database host |
| `RABBITMQ_HOST` | `localhost` | Container name | Message broker host |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | (not set) | S3 endpoint (MinIO vs R2) |
| `S3_BUCKET_NAME` | `genji-parkour-images` | `genji-parkour-images` | S3 bucket name |
| `S3_PUBLIC_URL` | `http://localhost:9000/genji-parkour-images` | `https://cdn.bkan0n.com` | Public URL for uploaded images |

## Troubleshooting

### Database Connection Errors

**Symptom**: `could not connect to server: Connection refused`

**Solution**:
1. Verify PostgreSQL is running:
   ```bash
   docker compose -f docker-compose.local.yml ps postgres-local
   ```
2. Check logs:
   ```bash
   docker compose -f docker-compose.local.yml logs postgres-local
   ```
3. Ensure `POSTGRES_HOST=localhost` in `.env.local`

### RabbitMQ Connection Errors

**Symptom**: `Connection to RabbitMQ failed`

**Solution**:
1. Verify RabbitMQ is healthy:
   ```bash
   docker compose -f docker-compose.local.yml ps rabbitmq-local
   ```
2. Check management UI: http://localhost:15672
3. Ensure `RABBITMQ_HOST=localhost` in `.env.local`

### MinIO Bucket Not Found

**Symptom**: `The specified bucket does not exist`

**Solution**:
Create the bucket:
```bash
mc alias set local http://localhost:9000 genji local_dev_password
mc mb local/genji-parkour-images
```

### Import Script SSH Errors

**Symptom**: `Cannot connect to genji-vps`

**Solution**:
1. Check SSH config exists: `~/.ssh/config`
2. Ensure entry exists:
   ```
   Host genji-vps
       HostName <vps-ip>
       User <username>
       IdentityFile ~/.ssh/your-key
   ```
3. Test SSH connection:
   ```bash
   ssh genji-vps
   ```

### Port Already in Use

**Symptom**: `Bind for 0.0.0.0:5432 failed: port is already allocated`

**Solution**:
1. Check what's using the port:
   ```bash
   lsof -i :5432  # PostgreSQL
   lsof -i :5672  # RabbitMQ
   lsof -i :9000  # MinIO
   ```
2. Stop the conflicting service or change the port in `docker-compose.local.yml`

## Stopping Services

Stop all infrastructure services:

```bash
docker compose -f docker-compose.local.yml down
```

Stop and remove volumes (fresh start):

```bash
docker compose -f docker-compose.local.yml down -v
```

## Next Steps

- [API Architecture](architecture.md) - Understand the codebase structure
- [Authentication](authentication.md) - How auth works
- [OpenAPI Reference](openapi.md) - API documentation
