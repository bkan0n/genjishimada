# Getting Started

This guide helps you run the project locally for development or testing.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.13+** - [Download Python](https://www.python.org/downloads/)
- **uv** - Fast Python package manager ([Installation Guide](https://github.com/astral-sh/uv))
- **Docker** - Required for PostgreSQL and RabbitMQ ([Get Docker](https://docs.docker.com/get-docker/))
- **just** - Command runner ([Installation Guide](https://github.com/casey/just))
- **Git** - Version control

## Installation

Follow these steps to set up the project:

### 1. Clone the Repository

```bash
git clone https://github.com/bkan0n/genjishimada.git
cd genjishimada
```

### 2. Install Dependencies

Use `just` to install all dependencies across the monorepo:

```bash
just setup
```

This command runs `uv sync --all-groups`, which installs dependencies for all workspaces (API, bot, SDK, and docs).

### 3. Configure Local Environment

Copy the local environment template and customize it:

```bash
cp .env.local.example .env.local
```

The `just run-api` and `just run-bot` commands automatically load `.env.local`.

Edit `.env.local` with your settings:

```env
# Discord (use a test bot token)
DISCORD_TOKEN=your_dev_bot_token_here
DISCORD_GUILD_ID=your_test_guild_id_here

# Database (already configured for local Docker services)
POSTGRES_HOST=localhost
POSTGRES_USER=genji
POSTGRES_PASSWORD=local_dev_password
POSTGRES_DB=genjishimada

# RabbitMQ (already configured for local Docker services)
RABBITMQ_HOST=localhost
RABBITMQ_USER=genji
RABBITMQ_PASS=local_dev_password

# MinIO (S3-compatible local storage)
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET_NAME=genji-parkour-images
S3_PUBLIC_URL=http://localhost:9000/genji-parkour-images
AWS_ACCESS_KEY_ID=genji
AWS_SECRET_ACCESS_KEY=local_dev_password

# API Key (for bot to call API)
API_KEY=local_dev_api_key

# Application
APP_ENVIRONMENT=local
```

### 4. Start Local Infrastructure

Start PostgreSQL, RabbitMQ, and MinIO for local development:

```bash
docker compose -f docker-compose.local.yml up -d
```

This starts:
- **PostgreSQL** on port 5432
- **RabbitMQ** on ports 5672 (AMQP) and 15672 (Management UI)
- **MinIO** on ports 9000 (API) and 9001 (Console)

### 5. Import Database from VPS (Optional)

If you want to work with production or development data locally:

```bash
# Import from dev environment
./scripts/import-db-from-vps.sh dev

# Or from production (be careful!)
./scripts/import-db-from-vps.sh prod
```

This requires SSH access to the VPS. See [SSH Configuration](#ssh-configuration) below.

### 6. Create MinIO Bucket

The first time you run MinIO, create the bucket:

```bash
# Install MinIO client (mc)
brew install minio/stable/mc  # macOS
# or download from https://min.io/docs/minio/linux/reference/minio-mc.html

# Configure MinIO client
mc alias set local http://localhost:9000 genji local_dev_password

# Create bucket
mc mb local/genji-parkour-images
```

## SSH Configuration

To import databases from the VPS, add an SSH config entry in `~/.ssh/config`:

```
Host genji-vps
    HostName your-vps-ip-or-hostname
    User your-username
    IdentityFile ~/.ssh/your-key
```

Ask a project maintainer for VPS connection details.

## Next Steps

Now that you've installed the project, learn how to:

- [Run the API and Bot](quickstart.md) - Start the services locally
- [Understand the Architecture](../bot/architecture/core-bot.md) - Learn how the system works
- [Make Your First Changes](../contributing/workflow.md) - Contributing guide

## Troubleshooting

### `uv` Not Found

If `uv` is not installed, follow the [official installation guide](https://github.com/astral-sh/uv).

### Docker Issues

Ensure Docker is running and you have sufficient resources allocated. On macOS, check Docker Desktop settings.

### Database Connection Errors

Verify that PostgreSQL is running:

```bash
docker compose -f docker-compose.local.yml ps postgres-local
```

Check logs if the container is not healthy:

```bash
docker compose -f docker-compose.local.yml logs postgres-local
```

### MinIO Connection Issues

Verify MinIO is running:

```bash
docker compose -f docker-compose.local.yml ps minio-local
```

Access the MinIO console at http://localhost:9001 (user: genji, password: local_dev_password)
