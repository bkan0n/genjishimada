# Configuration & Deployment

Use this page to wire environment variables, TOML configuration, and deployment workflows for the Genji Shimada bot.

## Environment configuration

Runtime settings come from a combination of environment variables and a TOML file loaded at startup.

### Core variables

Required environment variables in `.env`:

- `DISCORD_TOKEN` – Required by `bot.start()`. Obtain from [Discord Developer Portal](https://discord.com/developers/applications).
- `APP_ENVIRONMENT` – Controls the command prefix and which TOML file is loaded:
  - `"production"` → loads `configs/prod.toml`, uses `"?"` prefix
  - Any other value → loads `configs/dev.toml`, uses `"!"` prefix
- `API_KEY` – Forwarded to the `APIService` for authenticated requests to the API.
- API hostnames are derived from `APP_ENVIRONMENT` (`genjishimada-api-dev` for development, `genjishimada-api` for production).

### Queue variables

- `QUEUE_DATABASE_PASSWORD` — password for the restricted `genjishimada_queue_worker` login. With no URL override, the bot reuses the API's `POSTGRES_HOST` and `POSTGRES_DB` on port 5432. It never uses the API's `POSTGRES_USER` or `POSTGRES_PASSWORD`.
- `QUEUE_DATABASE_URL` — optional full PostgreSQL URL override; takes precedence over the shared database location and queue password. Local provisioning: `just queue-credentials-local` after applying migrations.
- `QUEUE_OPERATOR_IDS` — comma-separated Discord user IDs authorized to recover failed jobs; default `141372217677053952`. Set the same allowlist on API and bot. The API is authoritative.

Never use the API owner's PostgreSQL login for the bot. The queue migration installs storage and privileges; workers do not install schema at runtime.

### Optional observability variables

For error tracking and monitoring:

- `SENTRY_DSN` – Sentry DSN for error tracking
- `SENTRY_AUTH_TOKEN` – Sentry auth token (optional)
- `SENTRY_FEEDBACK_URL` – Custom feedback URL (optional)

## TOML configuration

The TOML schema is defined in `utilities/config.py` and covers guild, role, and channel identifiers.

### Development configuration

Edit `apps/bot/configs/dev.toml` for development IDs:

```toml
[guild]
id = 1234567890  # Your development Discord server ID

[channels]
newsfeed = 1234567890
completions_verification = 1234567890
completions_upvote = 1234567890
playtest = 1234567890
xp = 1234567890
logs = 1234567890

[roles]
admin = 1234567890
moderator = 1234567890
verified = 1234567890
```

### Production configuration

Edit `apps/bot/configs/prod.toml` for production IDs:

```toml
[guild]
id = 9876543210  # Production Discord server ID

[channels]
newsfeed = 9876543210
completions_verification = 9876543210
completions_upvote = 9876543210
playtest = 9876543210
xp = 9876543210
logs = 9876543210

[roles]
admin = 9876543210
moderator = 9876543210
verified = 9876543210
```

The `Genji` constructor reads the appropriate file on startup based on `APP_ENVIRONMENT`.

## Local development workflow

1. **Install dependencies**:
   ```bash
   just setup
   ```

2. **Configure environment**:
   ```bash
   cp .env.local.example .env.local
   # Edit .env.local with your Discord token and settings
   ```

3. **Edit development config**:
   ```bash
   # Edit apps/bot/configs/dev.toml with your Discord IDs
   ```

4. **Start infrastructure**:
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

   This starts PostgreSQL and MinIO for local development.

5. **Run the bot**:
   ```bash
   just run-bot
   ```

   The bot automatically loads `.env.local` and connects to the API at `localhost:8000`.

6. **Lint before committing**:
   ```bash
   just lint-bot
   ```

## Docker deployment

### Development

If you run the bot inside Docker:

```bash
docker compose -f docker-compose.dev.yml up -d genjishimada-bot-dev
```

### Production

Use the production compose file:

```bash
docker compose -f docker-compose.prod.yml up -d genjishimada-bot
```

## Deployment checklist

Before deploying to production:

- [ ] Update `configs/prod.toml` with production Discord IDs
- [ ] Set all required environment variables in production `.env`
- [ ] Ensure PostgreSQL queue and the Genji API are reachable
- [ ] Build and deploy the container image (or restart the process)
- [ ] Monitor Discord logs and Sentry events after rollout
- [ ] Verify bot appears online in Discord
- [ ] Test key commands and queue consumers

## Observability

### Logging

`setup_logging()` in `main.py` configures log levels and filters:

- Filters noisy Discord messages
- Enables DEBUG logs for internal packages when `APP_ENVIRONMENT` is `"development"`
- Logs to console by default

**View logs**:

```bash
# Local development
just run-bot

# Docker
docker compose -f docker-compose.prod.yml logs -f genjishimada-bot
```

### Sentry

`main()` initializes Sentry with trace and profile sampling when `SENTRY_DSN` is set:

```python
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration

sentry_sdk.init(
    dsn=SENTRY_DSN,
    environment=APP_ENVIRONMENT,
    integrations=[AsyncioIntegration()],
)
```

**Benefits**:
- Automatic exception capture
- Performance traces
- User context (Discord user info)

View errors at [sentry.io](https://sentry.io).

## Troubleshooting

### Bot Won't Start

**Check Discord token**:
```bash
# Verify DISCORD_TOKEN is set
echo $DISCORD_TOKEN
```

**Check permissions**:
- Ensure bot has required intents enabled in Discord Developer Portal
- Verify bot is invited to the server with correct permissions

**Check logs**:
```bash
docker compose -f docker-compose.prod.yml logs genjishimada-bot
```

### Queue Messages Not Processing

Check local PostgreSQL health and bot worker logs. Confirm the queue migration is applied and the queue-only login is provisioned. Run `just queue-credentials-local` for local credentials, then restart the bot. For remote failures, inspect the job's current diagnostic state through the recovery API or its operator alert. See [Queue operations](../../services/queue.md).

### API Requests Failing

**Verify API key**:
```bash
# Check API_KEY is set
echo $API_KEY
```

**Check API availability**:
```bash
curl -H "X-API-KEY: $API_KEY" http://localhost:8000/healthcheck
```

**Check bot logs**:
```bash
docker compose -f docker-compose.prod.yml logs genjishimada-bot | grep -i api
```

## Next Steps

- [Core Bot Lifecycle](../architecture/core-bot.md) - Understand bot startup
- [Services & Extensions](../architecture/services.md) - Learn about services
- [Operations Guide](../../operations/index.md) - Infrastructure overview
- [Docker Compose](../../operations/docker-compose.md) - Deployment guide
