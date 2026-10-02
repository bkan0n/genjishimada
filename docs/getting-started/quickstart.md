# Quick Start

Get the API and bot running locally in minutes.

!!! info "Prerequisites"
    This guide assumes you've completed the [Installation](installation.md) steps.

## Start Local Infrastructure

Start PostgreSQL and MinIO:

```bash
docker compose -f docker-compose.local.yml up -d
```

Verify all services are healthy:

```bash
docker compose -f docker-compose.local.yml ps
```

All services should show "Up (healthy)" status.

## Running the API

Start the Litestar API server:

```bash
just run-api
```

This command:
- Automatically loads `.env.local`
- Runs `litestar run` with hot reload enabled
- Serves on `http://localhost:8000`

### Verify API is Running

Open your browser to:

- **API Docs**: [http://localhost:8000/schema](http://localhost:8000/schema)
- **Health Check**: [http://localhost:8000/healthcheck](http://localhost:8000/healthcheck)

You should see the interactive OpenAPI documentation.

## Running the Bot

Start the Discord bot:

```bash
just run-bot
```

This command:
- Automatically loads `.env.local`
- Runs the bot with your configured Discord token
- Connects to the local API at `localhost:8000`

### Verify Bot is Running

Check the terminal output for:

```
Logged in as YourBotName#1234
Bot is ready.
```

In your Discord server, the bot should appear online.

## Testing the Integration

### 1. Trigger a Bot Command

In Discord, send a command to test the bot:

```
/map search parkour
```

### 2. Check API Logs

In the API terminal, you should see incoming requests from the bot.

### 3. Verify background work

Run `just test-queue-fast` for backend queue acceptance. Run `just test-queue` to include isolated process and database failure tests. The full suite does not connect to Discord or require live service credentials.

## Development Workflow

### Make Code Changes

The API runs with `--reload`, so changes are automatically picked up. For the bot, you'll need to restart the process (Ctrl+C and run `just run-bot` again).

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
docker compose -f docker-compose.local.yml logs -f postgres-local
```


**MinIO logs**:
```bash
docker compose -f docker-compose.local.yml logs -f minio-local
```

### Stop Services

Stop infrastructure services:

```bash
docker compose -f docker-compose.local.yml down
```

Stop API/bot: Press `Ctrl+C` in their respective terminals.

### Re-sync Dependencies

After pulling changes or switching branches:

```bash
just sync
```

## Next Steps

- [Local Development Guide](../api/local-development.md) - Detailed local development documentation
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

1. Verify `DISCORD_TOKEN` is set in `.env.local`
2. Check that the bot has proper permissions in your Discord server
3. Ensure intents are enabled in the [Discord Developer Portal](https://discord.com/developers/applications)

### Database Connection Failed

1. Verify Docker services are running:
   ```bash
   docker compose -f docker-compose.local.yml ps
   ```

2. Check PostgreSQL logs:
   ```bash
   docker compose -f docker-compose.local.yml logs postgres-local
   ```

3. Verify database credentials in `.env.local`:
   ```
   POSTGRES_HOST=localhost
   POSTGRES_USER=genji
   POSTGRES_PASSWORD=local_dev_password
   POSTGRES_DB=genjishimada
   ```

### Queue Connection Failed

Check PostgreSQL health and apply the queue migration. Run `just queue-credentials-local` to set the queue-only login and update `.env.local`, then restart the bot. See [Queue operations](../services/queue.md).

### MinIO Connection Failed

1. Verify MinIO is healthy:
   ```bash
   docker compose -f docker-compose.local.yml ps minio-local
   ```

2. Ensure bucket exists (see [Installation Guide](installation.md#9-create-minio-bucket))
