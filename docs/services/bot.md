# Bot Service

The Genji bot is a Discord application that interacts with players, moderators, and developers.
It integrates with the REST API and RabbitMQ to deliver real-time updates, handle completions and playtests, and manage user notifications.

## What the bot does

- Listens for events from RabbitMQ and processes them (newsfeed posts, completions, playtest updates, XP grants).
- Provides slash commands and context menus for players and moderators on Discord.
- Posts embeds to channels and threads when new maps, records, guides, or announcements are created.
- Handles playtest voting and updates rank cards in real time.
- Maintains user state by calling the API.

## Technologies used

| Technology    | Purpose |
|-------------|---------|
| `discord.py` | Asynchronous Discord bot framework. |
| `aiohttp`    | HTTP client used by the API service. |
| `aio-pika`   | RabbitMQ client library for consuming and publishing. |
| `msgspec`    | Fast serialization of request and response models. |
| `sentry_sdk` | Error tracking and performance monitoring. |

## How it is started

The entry point in `apps/bot/main.py` configures Sentry and logging, then creates a `Genji` bot instance and starts it with the Discord token. A prefix of `?` is used in production and `!` otherwise. The `Genji` class loads extensions during `setup_hook` and schedules `rabbit.start()` to begin queue consumption.

## Services injected

Extensions attach services to the bot via an async `setup` function. The `Genji` class defines properties for each service (API, newsfeed, playtests, completions, XP, notifications, Rabbit, and thumbnail service) so they can be accessed from commands and other services.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `DISCORD_TOKEN` | Bot token provided by Discord; required to start the bot. |
| `APP_ENVIRONMENT` | `production` or `development`; affects logging and prefixes. |
| `RABBITMQ_USER` / `RABBITMQ_PASS` / `RABBITMQ_HOST` | Credentials for connecting to RabbitMQ. |
| `SENTRY_DSN` | DSN for Sentry error tracking. |

## Related pages

- [Bot Overview](../bot/index.md)
- [Newsfeed Pattern](../bot/ux/newsfeed-and-embeds.md)
- [RabbitMQ Consumers](../bot/architecture/messaging.md)
