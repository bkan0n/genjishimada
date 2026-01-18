# Data Models

This page highlights the major SDK modules and representative models. For full definitions, see the source in `libs/sdk/src/genjishimada_sdk/`.

## Module Map

- `genjishimada_sdk.maps` - Maps, playtests, map edits, and statistics
- `genjishimada_sdk.completions` - Completion submissions, leaderboards, and OCR
- `genjishimada_sdk.users` - User profiles and community leaderboard data
- `genjishimada_sdk.notifications` - Notification payloads and events
- `genjishimada_sdk.newsfeed` - Newsfeed events and payloads
- `genjishimada_sdk.xp` - XP events and grants
- `genjishimada_sdk.lootbox` - Lootbox metadata and rewards
- `genjishimada_sdk.auth` - Auth-related request/response models

## Representative Models

### Maps

**`MapResponse`** (`genjishimada_sdk.maps`)

Represents a full map record returned by the API. Fields include:

- `id`, `code`, `map_name`, `difficulty`
- `creators`, `checkpoints`, `official`, `archived`
- `playtesting`, `ratings`, `guides`, `raw_difficulty`

### Completions

**`CompletionResponse`** (`genjishimada_sdk.completions`)

Represents a completion entry and its verification metadata. Fields include:

- `code`, `user_id`, `name`, `time`
- `screenshot`, `video`, `verified`, `rank`
- `difficulty`, `medal`, `message_id`

### Users

**`UserResponse`** (`genjishimada_sdk.users`)

Represents a user profile. Fields include:

- `id`, `global_name`, `nickname`
- `overwatch_usernames`, `coalesced_name`
- `coins`

### Notifications

**`NotificationDeliveryEvent`** (`genjishimada_sdk.notifications`)

Event published to queue consumers when a notification should be delivered.

### Events

Most event models end in `Event` (for example `CompletionCreatedEvent`, `NewsfeedDispatchEvent`, `PlaytestCreatedEvent`) and are used for RabbitMQ payloads.

## Tips for Working with Models

- Use `msgspec` for fast validation and serialization.
- Prefer SDK models in API responses and RabbitMQ payloads to avoid schema drift.
- When in doubt, inspect the model definition in `libs/sdk/src/genjishimada_sdk/`.

## Next Steps

- [Usage Examples](usage.md)
- [API Documentation](../api/index.md)
- [Bot Messaging](../bot/architecture/messaging.md)
