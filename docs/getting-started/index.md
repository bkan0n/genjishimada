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

### 3. Configure Environment Variables

Create a `.env` file in the repository root and set the required variables:

```env
# Discord
DISCORD_TOKEN=your_discord_bot_token

# Database
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=your_password
POSTGRES_DB=genjishimada

# RabbitMQ
RABBITMQ_USER=admin
RABBITMQ_PASS=your_password
RABBITMQ_HOST=localhost

# API
API_KEY=your_api_key_for_bot
APP_ENVIRONMENT=development

# S3-compatible storage (Cloudflare R2)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
R2_ACCOUNT_ID=your_r2_account_id

# Email
RESEND_API_KEY=your_resend_key

# Monitoring
SENTRY_DSN=your_sentry_dsn
```

If you are running the API on the host, set `PSQL_DSN` to point at the local Postgres port:

```env
PSQL_DSN=postgresql://genjishimada:your_password@localhost:65432/genjishimada
```

### 4. Start Infrastructure Services

Start the database and RabbitMQ only:

```bash
docker compose -f docker-compose.dev.yml up -d \
  genjishimada-db-dev \
  genjishimada-rabbitmq-dev
```

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
docker compose -f docker-compose.dev.yml ps genjishimada-db-dev
```

Check logs if the container is not healthy:

```bash
docker compose -f docker-compose.dev.yml logs genjishimada-db-dev
```
