# Bot Documentation

The Genji Shimada Discord bot is built with **discord.py** and provides interactive features for the Genji Parkour community.

## Overview

The bot handles:

- **User commands** - Interactive Discord slash commands
- **Event processing** - Async message queue consumers
- **Notifications** - Discord notifications for completions, maps, and achievements
- **Integration** - Seamless integration with the REST API

## Quick Links

<div class="grid cards" markdown>

-   :material-robot:{ .lg .middle } **Architecture**

    ---

    Learn how the bot is structured

    [:octicons-arrow-right-24: Core Bot](architecture/core-bot.md)

-   :material-message:{ .lg .middle } **Messaging**

    ---

    Understand RabbitMQ queue consumers

    [:octicons-arrow-right-24: Messaging](architecture/messaging.md)

-   :material-cog:{ .lg .middle } **Configuration**

    ---

    Configure the bot for your environment

    [:octicons-arrow-right-24: Configuration](operations/configuration.md)

</div>

## Key Features

### Slash Commands

The bot uses Discord's slash commands for user interaction:

```python
@app_commands.command(name="map")
async def map_command(interaction: discord.Interaction, map_code: str):
    """Search for a map by code."""
    ...
```

### Queue Consumers

The bot consumes events from RabbitMQ:

```python
@queue_consumer("api.completion.submission", struct_type=CompletionCreatedEvent)
async def handle_completion(event: CompletionCreatedEvent, message: AbstractIncomingMessage) -> None:
    # Send Discord notification
    ...
```

### API Integration

The bot calls the API through `APIService` attached to `bot.api`:

```python
map_data = await bot.api.get_map(map_code)
```

## Bot Structure

```
apps/bot/
├── core/
│   └── genji.py           # Main bot class
├── extensions/            # Feature modules
│   ├── rabbit.py          # RabbitMQ service
│   ├── api_service.py     # API client
│   ├── completions.py     # Completion handlers
│   └── ...
├── configs/               # Configuration files
│   ├── dev.toml
│   └── prod.toml
└── main.py                # Entry point
```

## Running the Bot

### Local Development

Run the bot natively for fast iteration:

```bash
just run-bot
```

This automatically loads `.env.local` and connects to infrastructure running in `docker-compose.local.yml`.

See the [Quick Start Guide](../getting-started/quickstart.md) for full local development setup.

### Remote Staging

For deploying to a remote staging server:

```bash
docker compose -f docker-compose.dev.yml up -d genjishimada-bot-dev
```

### Remote Production

For deploying to a remote production server:

```bash
docker compose -f docker-compose.prod.yml up -d genjishimada-bot
```

## Next Steps

- [Core Bot Architecture](architecture/core-bot.md) - Understand the bot's structure
- [Messaging System](architecture/messaging.md) - Learn about queue consumers
- [Services](architecture/services.md) - Explore shared services
- [Configuration](operations/configuration.md) - Configure the bot
