# Core Bot Lifecycle

This page details how the main Discord process boots, wires shared services, and loads extensions.

## Entry point

The bot starts in `apps/bot/main.py` inside the `main()` coroutine. The sequence is:

1. Configure Sentry (when `SENTRY_DSN` is present) and set up filtered Discord logging via `setup_logging()`.
2. Create an `aiohttp.ClientSession` and instantiate `core.Genji`, passing the configured prefix (`"?"` in production, `"!"` otherwise).
3. Start the asynchronous context manager for the bot and call `bot.start(DISCORD_TOKEN)` to connect to the Discord gateway.

`core/genji.py` defines the `Genji` subclass of `commands.Bot`. During `__init__` the class:

- Applies the gateway intents defined at module level.
- Stores the shared HTTP session and constructs a `VideoThumbnailService` helper.
- Loads `configs/prod.toml` when `APP_ENVIRONMENT` is `"production"`, or `configs/dev.toml` for all other environments, using the `utilities.config.decode` helper.

## Extension loading

`Genji.setup_hook` runs once the Discord connection is preparing. It loads every module under `extensions/` (discovered via `pkgutil` in `extensions.__init__.EXTENSIONS`) plus the debugging cog `jishaku`. After extensions are loaded, the method schedules `self.rabbit.start()` on the bot loop so that queue consumers begin once all handlers are registered.

Each extension exposes an async `setup(bot)` function that attaches services or cogs to the bot. Notable patterns include:

- `extensions.api_service.setup` instantiates `APIService` and assigns it to `bot.api` for use across other modules.
- `extensions.newsfeed.setup`, `extensions.completions.setup`, `extensions.playtest.setup`, and `extensions.xp.setup` create service classes that are stored on the bot for later access.
- `extensions.notifications.setup` attaches `NotificationService` to `bot.notifications`.
- `extensions.rabbit.setup` prepares the `RabbitService`, which `setup_hook` starts after all handlers are registered.

## Service lifecycle

Service classes that inherit from `utilities.base.BaseService` (for example `CompletionsService`, `PlaytestService`, and `XPService`) lazily resolve the configured guild and their target channels. The base class spawns a task that waits for the bot to become ready, fetches `bot.config.guild`, and calls each service's `_resolve_channels()` hook before handling work.

When adding a new feature module:

1. Create an extension module under `extensions/` with an `async def setup(bot)` entry point.
2. Attach any long-lived service to the bot (optionally inheriting from `BaseService`).
3. Register queue handlers with `queue_consumer` if the feature processes RabbitMQ events (see [Messaging & Queues](messaging.md)).
4. Ensure the module is importable so that `extensions.__init__` discovers it automatically during startup.

## File Locations

All bot code is located in `apps/bot/`:

```
apps/bot/
├── main.py               # Entry point
├── core/
│   └── genji.py          # Main bot class
├── extensions/           # Feature modules
│   ├── __init__.py       # Extension discovery
│   ├── api_service.py    # API client
│   ├── rabbit.py         # RabbitMQ service
│   ├── newsfeed.py       # Newsfeed service
│   ├── completions.py    # Completions service
│   ├── playtest.py       # Playtest service
│   ├── notifications.py  # Notification service
│   └── xp.py             # XP service
├── utilities/            # Shared utilities
│   ├── base.py           # BaseService
│   ├── config.py         # Config schema
│   └── formatter.py      # Embed formatters
└── configs/              # TOML configuration
    ├── dev.toml
    └── prod.toml
```

## Next Steps

- [Services & Extensions](services.md) - Understand the service architecture
- [Messaging & Queues](messaging.md) - Learn about queue consumers
- [Configuration](../operations/configuration.md) - Configure the bot
