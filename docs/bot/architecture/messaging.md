# Messaging & Queues

The bot consumes RabbitMQ queues to react to events emitted by the Genji Parkour API. Queue handlers live alongside
their feature modules and are registered through a shared decorator.

## RabbitMQ integration

- `extensions/_queue_registry.py` provides `queue_consumer`, which wraps handlers with decoding, idempotency, and pytest
  short-circuit logic.
- `extensions/rabbit.RabbitHandler` opens pooled connections to RabbitMQ, declares queues (and matching dead-letter
  queues), wraps handlers for error handling, and tracks startup drain state. The client is created during the
  `extensions.rabbit` setup hook and started from `Genji.setup_hook`.
- Services can call `await bot.rabbit.wait_until_drained()` when they need to delay work until any startup backlog has
  been processed (for example, before sending verification embeds or playtest updates).

## Queue handler lifecycle

1. Decorate an async function or method with `@queue_consumer("queue-name", struct_type=...)` inside the relevant
   extension module.
2. Parse the message body with `msgspec` models before touching Discord state.
3. Perform the required Discord or API calls. The wrapper created by `RabbitHandler` manages acknowledgements and
   ensures failures are logged before the message is dead-lettered.

## Queue naming convention

Queues follow the pattern: `api.<domain>.<action>`

Examples:

- `api.newsfeed.create`
- `api.completion.submission`
- `api.playtest.create`

## Queue catalog

| Queue                                    | Handler                                                  | Notes                                                                  |
|------------------------------------------|----------------------------------------------------------|------------------------------------------------------------------------|
| `api.newsfeed.create`                    | `NewsfeedHandler._process_newsfeed_create`               | Fetches the new event and posts it to the configured newsfeed channel. |
| `api.notification.delivery`              | `NotificationHandler._process_notification_delivery`     | Sends DMs or channel notifications based on user settings.             |
| `api.completion.autoverification.failed` | `CompletionHandler._process_autoverification_failed`     | Handles failed autoverification results.                               |
| `api.completion.upvote`                  | `CompletionHandler._process_update_upvote_message`       | Forwards completion submissions into the upvote channel.               |
| `api.completion.submission`              | `CompletionHandler._process_create_submission_message`   | Builds the verification queue embed for a new completion submission.   |
| `api.completion.verification`            | `CompletionHandler._process_verification_status_change`  | Updates verification state and notifies users.                         |
| `api.playtest.create`                    | `PlaytestHandler._process_create_playtest_message`       | Creates playtest threads and posts the intake embed.                   |
| `api.playtest.vote.cast`                 | `PlaytestHandler._process_vote_cast_message`             | Records a new playtest vote and grants XP.                             |
| `api.playtest.vote.remove`               | `PlaytestHandler._process_vote_remove_message`           | Handles vote removal events.                                           |
| `api.playtest.approve`                   | `PlaytestHandler._process_playtest_approve_message`      | Posts approval summaries and cleans up playtest state.                 |
| `api.playtest.force_accept`              | `PlaytestHandler._process_playtest_force_accept_message` | Mirrors force-accept commands issued upstream.                         |
| `api.playtest.force_deny`                | `PlaytestHandler._process_playtest_force_deny_message`   | Mirrors force-deny commands issued upstream.                           |
| `api.playtest.reset`                     | `PlaytestHandler._process_playtest_reset_message`        | Resets playtest runs and refreshes Discord embeds.                     |
| `api.xp.grant`                           | `XPHandler._process_grant_message`                       | Applies XP rewards announced by the API.                               |
| `api.map_edit.created`                   | `MapEditHandler._process_edit_created`                   | Creates a verification view for new map edit requests.                 |
| `api.map_edit.resolved`                  | `MapEditHandler._process_edit_resolved`                  | Cleans up the verification queue message once resolved.                |

Keep this table current as new queues are introduced so on-call maintainers can trace message flow quickly.

## Idempotency

Most queues enforce idempotency using `message_id` headers:

**API side** (publishing):

```python
await self.publish_message(
    queue_name="api.completion.submission",
    message=event,
    message_id=f"completion-{completion_id}",  # Unique ID
)
```

**Bot side** (consuming):

```python
@queue_consumer("api.completion.submission", struct_type=CompletionCreatedEvent, idempotent=True)
async def handle_completion(self, event: CompletionCreatedEvent, message: AbstractIncomingMessage) -> None:
    # Handler only runs once per message_id
    ...
```

Claims are tracked in the database to prevent duplicate processing.

## Pytest short-circuit

Queue consumers skip processing when a message header includes `x-pytest-enabled: 1`. This is used in integration tests
to avoid side effects.

## Dead Letter Queue (DLQ)

Failed messages are moved to a dead letter queue (e.g., `api.completion.submission.dlq`) after exhausting retries.

**DLQ Processor** (runs every 60 seconds):

1. Checks DLQ for messages
2. Posts alert to Discord with message details
3. Marks message with `dlq_notified` header
4. Prevents duplicate alerts

## Next Steps

- [Core Bot Lifecycle](core-bot.md) - Understand how the bot starts
- [Services & Extensions](services.md) - Learn about service architecture
- [SDK Documentation](../../sdk/index.md) - See the msgspec event models
