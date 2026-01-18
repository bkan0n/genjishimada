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

### RabbitMQ variables

Required for message queue integration:

- `RABBITMQ_USER` – RabbitMQ username
- `RABBITMQ_PASS` – RabbitMQ password
- `RABBITMQ_HOST` – RabbitMQ host (e.g., `localhost` or `genjishimada-rabbitmq` in Docker)

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

2. **Configure environment**: create a `.env` file and add your variables.

3. **Edit development config**:
   ```bash
   # Edit apps/bot/configs/dev.toml with your Discord IDs
   ```

4. **Start infrastructure**:
   ```bash
   docker compose -f docker-compose.dev.yml up -d \
     genjishimada-db-dev \
     genjishimada-rabbitmq-dev
   ```

5. **Run the bot**:
   ```bash
   docker compose -f docker-compose.dev.yml up -d genjishimada-bot-dev
   ```

   If you run the bot on the host with `just run-bot`, ensure the API hostname (`genjishimada-api-dev`) resolves locally.

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
- [ ] Ensure RabbitMQ and the Genji API are reachable
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

**Verify RabbitMQ connection**:
```bash
# Check RabbitMQ is running
docker compose -f docker-compose.dev.yml ps genjishimada-rabbitmq-dev

# Check bot logs for connection errors
docker compose -f docker-compose.prod.yml logs genjishimada-bot | grep -i rabbitmq
```

**Check queue consumers**:
- Inspect bot logs for queue bindings and errors

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
