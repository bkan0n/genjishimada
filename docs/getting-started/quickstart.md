# Quick Start

Get the API and bot running locally in minutes.

!!! info "Prerequisites"
    This guide assumes you've completed the [Installation](installation.md) steps and have Docker services running.

## Running the API

Start the Litestar API server:

```bash
just run-api
```

This command:
- Changes to the `apps/api` directory
- Runs `litestar run` with hot reload enabled
- Serves on `http://localhost:8000`

If you are running the API on the host, set `PSQL_DSN` in `.env` so it points at `localhost:65432`.

### Verify API is Running

Open your browser to:

- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/healthcheck](http://localhost:8000/healthcheck)

You should see the interactive OpenAPI documentation.

## Running the Bot

The bot is configured to call the API at the Docker service name (`genjishimada-api-dev` in development). The simplest local setup is to run the bot in Docker:

```bash
docker compose -f docker-compose.dev.yml up -d genjishimada-bot-dev
```

If you run the bot on the host with `just run-bot`, ensure the API hostname resolves (for example by running the API container and joining the same Docker network).

### Verify Bot is Running

Check the terminal output for:

```
Logged in as YourBotName#1234
Bot is ready.
```

In your Discord server, the bot should appear online.

## Running Both Services in Docker (optional)

If you want Docker to run everything:

```bash
docker compose -f docker-compose.dev.yml up -d
```

This will start API, bot, database, and RabbitMQ in containers.

## Testing the Integration

### 1. Trigger a Bot Command

In Discord, send a command to test the bot:

```
/map search parkour
```

### 2. Check API Logs

In the API terminal, you should see incoming requests from the bot.

### 3. Check RabbitMQ

RabbitMQ is not exposed directly in this repo; it is typically proxied via Caddy in production. For local checks, use container logs:

```bash
docker compose -f docker-compose.dev.yml logs -f genjishimada-rabbitmq-dev
```

## Development Workflow

### Make Code Changes

The API runs with `--reload`, so changes are automatically picked up. For the bot, you'll need to restart the process.

### Run Tests

Test the API:

```bash
just test-api
```

This runs pytest with 8 parallel workers.

### Lint Code

Before committing, run linters:

```bash
just lint-all
```

This formats code with Ruff and type-checks with BasedPyright.

## Common Tasks

### View Logs

**API logs**: Displayed in the terminal where `just run-api` is running

**Bot logs**: Displayed in the terminal where `just run-bot` is running

**Database logs**:
```bash
docker compose -f docker-compose.dev.yml logs -f genjishimada-db-dev
```

**RabbitMQ logs**:
```bash
docker compose -f docker-compose.dev.yml logs -f genjishimada-rabbitmq-dev
```

### Stop Services

Stop Docker services:

```bash
docker compose -f docker-compose.dev.yml down
```

Stop API/bot: Press `Ctrl+C` in their respective terminals.

### Re-sync Dependencies

After pulling changes or switching branches:

```bash
just sync
```

## Next Steps

- [Bot Architecture](../bot/architecture/core-bot.md) - Understand how the bot works
- [API Documentation](../api/index.md) - Learn about API endpoints
- [Contributing Guide](../contributing/workflow.md) - Make your first contribution

## Troubleshooting

### Port Already in Use

If port 8000 is already in use, find and kill the process:

```bash
lsof -ti:8000 | xargs kill -9
```

### Bot Won't Connect

1. Verify `DISCORD_TOKEN` is set in `.env`
2. Check that the bot has proper permissions in your Discord server
3. Ensure intents are enabled in the [Discord Developer Portal](https://discord.com/developers/applications)

### Database Connection Failed

1. Verify Docker services are running:
   ```bash
   docker compose -f docker-compose.dev.yml ps
   ```

2. Check PostgreSQL logs:
   ```bash
   docker compose -f docker-compose.dev.yml logs genjishimada-db-dev
   ```

3. Verify database credentials in `.env` match `docker-compose.dev.yml`
