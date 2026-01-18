# Services & Extensions

Services encapsulate long-lived Discord behaviour, while extensions expose the asynchronous `setup` hook that registers those services and any associated cogs.

## Service catalog

| Service | Module / Class | Responsibilities |
| --- | --- | --- |
| API client | `extensions/api_service.py` → `APIService` | Maintains an authenticated `aiohttp` session to the API and exposes helpers for maps, completions, playtests, and notifications. Stored on `bot.api`. |
| RabbitMQ | `extensions/rabbit.py` → `RabbitService` | Connects to RabbitMQ using pooled channels, declares queues (and DLQs), wraps handlers registered through `queue_consumer`, and exposes helpers such as `publish` and `wait_until_drained`. Stored on `bot.rabbit`. |
| Notifications | `extensions/notifications.py` → `NotificationService` | Determines whether a user has opted into specific notification bitmasks and sends DMs or channel pings accordingly. Stored on `bot.notifications`. |
| Newsfeed | `extensions/newsfeed.py` → `NewsfeedService` | Registers builders for each newsfeed payload type, publishes events into the configured channel, and consumes `api.newsfeed.create` messages. Stored on `bot.newsfeed`. |
| Completions | `extensions/completions.py` → `CompletionsService` | Resolves verification channels, renders verification views, emits follow-up newsfeed events, and handles completion-related queues. Stored on `bot.completions`. |
| Playtest | `extensions/playtest.py` → `PlaytestService` | Manages playtest threads, queue-driven state changes, and XP grants tied to votes. Stored on `bot.playtest`. |
| XP | `extensions/xp.py` → `XPService` | Resolves XP channels, applies XP grants from the `api.xp.grant` queue, and exposes helpers for other services to award XP. Stored on `bot.xp`. |
| Map edits | `extensions/moderator.py` → `MapEditorService` | Manages map edit verification views and listens to map edit queues. Stored on `bot.map_editor`. |
| Thumbnails | `extensions/video_thumbnail.py` → `VideoThumbnailService` | Generates video thumbnails for embeds and newsfeed entries. Stored on `bot.thumbnail_service`. |

> Extend this table as new extensions ship so there is a single map of the long-lived services attached to the bot instance.

## Extension anatomy

1. **Setup hook:** Each extension defines `async def setup(bot)` and attaches services, cogs, or background tasks.
2. **Shared state:** Services either use property setters on `Genji` (for example `bot.api`) or inherit from `utilities.base.BaseService` to gain guild/channel resolution helpers.
3. **Queue registration:** Background work is tied to RabbitMQ queues by decorating handler coroutines with `@queue_consumer("queue-name")`.
4. **Cross-extension collaboration:** Services call into one another via the properties on `bot`. For example, the completions flow calls `bot.api` to fetch payloads, uses `bot.notifications` to determine DM preferences, and leverages `bot.xp` to grant XP during verification updates.

## BaseService

The `utilities.base.BaseService` class provides common functionality for services:

```python
from utilities.base import BaseService

class MyService(BaseService):
    async def _resolve_channels(self) -> None:
        """Called after bot is ready and guild is resolved."""
        self.my_channel = await self.guild.fetch_channel(channel_id)

    async def do_work(self) -> None:
        """Service methods can access self.guild and resolved channels."""
        await self.my_channel.send("Hello!")
```

**Features**:
- Automatic guild resolution
- Channel resolution hook
- Access to bot instance

## Creating a New Extension

To add a new feature to the bot:

1. **Create the extension file**:
   ```
   apps/bot/extensions/my_feature.py
   ```

2. **Define the setup function**:
   ```python
   async def setup(bot):
       service = MyService(bot)
       bot.my_service = service
   ```

3. **Optionally create a service**:
   ```python
   from utilities.base import BaseService

   class MyService(BaseService):
       async def _resolve_channels(self) -> None:
           # Resolve channels here
           pass
   ```

4. **Register queue handlers** (if needed):
   ```python
   from extensions._queue_registry import queue_consumer

   @queue_consumer("api.my_feature.event", struct_type=MyEvent)
   async def handle_event(self, event: MyEvent, message: AbstractIncomingMessage):
       # Process the event
       pass
   ```

5. **Import in `extensions/__init__.py`**:
   ```python
   EXTENSIONS = [
       # ...
       "extensions.my_feature",
   ]
   ```

Document queues, commands, and presentation helpers in the relevant sections when adding new functionality so future contributors can follow the established patterns.

## Next Steps

- [Core Bot Lifecycle](core-bot.md) - Understand bot startup
- [Messaging & Queues](messaging.md) - Learn about queue handlers
- [Newsfeed & Embeds](../ux/newsfeed-and-embeds.md) - UI guidelines
- [Configuration](../operations/configuration.md) - Configure the bot
