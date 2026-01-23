# Handlers & Extensions

Services encapsulate long-lived Discord behaviour, while extensions expose the asynchronous `setup` hook that registers
those services and any associated cogs.

## Service catalog

| Service       | Module / Class                                        | Responsibilities                                                                                                                                                                                                                                                               |
|---------------|-------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| API client    | `extensions/api_service.py` → `APIService`            | Maintains an authenticated `aiohttp` session to the GenjiPK API, performs JSON encoding/decoding with `msgspec`, and exposes helpers for maps, completions, playtests, and notifications. The instance is assigned to `bot.api` during setup so other extensions can reuse it. 
| RabbitMQ      | `extensions/rabbit.py` → `RabbitHandler`              | Connects to RabbitMQ using pooled channels, declares queues (and their DLQs), wraps handlers registered through `register_queue_handler`, and exposes helper utilities such as `publish` and `wait_until_drained`. Assigned to `bot.rabbit` in the extension setup.            
| Notifications | `extensions/notifications.py` → `NotificationHandler` | Determines whether a user has opted into specific notification bitmasks and sends DMs or channel pings accordingly. Stored on `bot.notifications` for use by other features.                                                                                                   
| Newsfeed      | `extensions/newsfeed.py` → `NewsfeedHandler`          | Registers builders for each newsfeed payload type, publishes events into the configured channel, and consumes `api.newsfeed.create` queue messages to mirror content from the API. Attached to `bot.newsfeed` by the extension setup.                                          
| Completions   | `extensions/completions.py` → `CompletionHandler`     | Resolves submission, verification, and upvote channels; renders verification views; emits follow-up newsfeed events; and handles the completion-related RabbitMQ queues. The setup function assigns it to `bot.completions`.                                                   
| Playtest      | `extensions/playtest.py` → `PlaytestHandler`          | Manages playtest threads, queue-driven state changes, and XP grants tied to votes. Registered on `bot.playtest` in the extension setup.                                                                                                                                        
| XP            | `extensions/xp.py` → `XPHandler`                      | Resolves XP channels, applies XP grants from the `api.xp.grant` queue, and exposes helpers for other services to award XP by type. Stored on `bot.xp` during setup.                                                                                                            

> Extend this table as new extensions ship so there is a single map of the long-lived services attached to the bot
> instance.

## Extension anatomy

1. **Setup hook:** Each extension defines `async def setup(bot)` and attaches services, cogs, or background tasks.
2. **Shared state:** Handlers either use property setters on `Genji` (for example `bot.api`) or inherit from
   `utilities.base.BaseHandler` to gain guild/channel resolution helpers.
3. **Queue registration:** Background work is tied to RabbitMQ queues by decorating handler coroutines with
   `@register_queue_handler("queue-name")`. The decorator stores metadata so `RabbitHandler` can bind the functions when
   it starts consuming.
4. **Cross-extension collaboration:** Handlers call into one another via the properties on `bot`. For example, the
   completions flow calls `bot.api` to fetch payloads, uses `bot.notifications` to determine DM preferences, and
   leverages `bot.xp` to grant XP during verification updates.

Document queues, commands, and presentation helpers in the relevant sections below when adding new functionality so
future contributors can follow the established patterns.
