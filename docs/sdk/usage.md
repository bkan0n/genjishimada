# SDK Usage

Common patterns and examples for using the Genji Shimada SDK.

## Installation

The SDK is a workspace member and is available automatically in API and bot code after:

```bash
just setup
```

## Basic Usage

### Import Models

```python
from genjishimada_sdk.users import UserCreateRequest, UserResponse
from genjishimada_sdk.maps import MapResponse
from genjishimada_sdk.completions import CompletionResponse
```

### Create Instances

Use request models when constructing payloads:

```python
from genjishimada_sdk.users import UserCreateRequest

payload = UserCreateRequest(
    id=1234567890,
    global_name="Player",
    nickname="Player",
)
```

### Deserialize API Responses

```python
import msgspec
import httpx
from genjishimada_sdk.maps import MapResponse

async with httpx.AsyncClient() as client:
    response = await client.get(
        "https://api.genji.pk/api/v3/maps/ABC123",
        headers={"X-API-KEY": api_key},
    )

    map_data = msgspec.json.decode(response.content, type=MapResponse)
    print(map_data.map_name, map_data.difficulty)
```

## API Patterns

### Request Handlers

Use SDK models for request/response bodies:

```python
from litestar import post
from genjishimada_sdk.users import UserCreateRequest, UserResponse

@post("/users")
async def create_user(data: UserCreateRequest) -> UserResponse:
    # Insert into database and return a UserResponse
    return await create_user_in_db(data)
```

### Publishing Events

Publish SDK event models to RabbitMQ:

```python
from genjishimada_sdk.completions import CompletionCreatedEvent
from di.base import BaseService

class CompletionsService(BaseService):
    async def create_completion(self, user_id: int, map_id: int) -> int:
        completion_id = await insert_completion(...)

        event = CompletionCreatedEvent(
            completion_id=completion_id,
        )

        await self.publish_message(
            queue_name="api.completion.submission",
            message=event,
        )

        return completion_id
```

## Bot Patterns

### Queue Consumers

Consume SDK event models from RabbitMQ:

```python
from extensions._queue_registry import queue_consumer
from genjishimada_sdk.completions import CompletionCreatedEvent
from aio_pika.abc import AbstractIncomingMessage

@queue_consumer(
    "api.completion.submission",
    struct_type=CompletionCreatedEvent,
    idempotent=True,
)
async def handle_completion(
    self,
    event: CompletionCreatedEvent,
    message: AbstractIncomingMessage,
) -> None:
    print(f"Completion {event.completion_id} submitted")
```

## Validation

### Type Validation

`msgspec` validates types at runtime:

```python
from genjishimada_sdk.users import UserCreateRequest

# Valid
payload = UserCreateRequest(id=1, global_name="Player", nickname="Player")

# Invalid - raises ValidationError
payload = UserCreateRequest(id="not_an_int", global_name="Player", nickname="Player")
```

## Advanced Patterns

### Partial Updates

Use dictionaries for partial updates:

```python
import msgspec
from genjishimada_sdk.users import UserResponse

user = UserResponse(id=1, global_name="Player", nickname="Player", overwatch_usernames=None)
updates = {"coins": 200}
updated_user = msgspec.structs.replace(user, **updates)
```

## Next Steps

- [Data Models](data-models.md) - Module overview
- [API Documentation](../api/index.md) - See SDK models in API endpoints
- [Bot Messaging](../bot/architecture/messaging.md) - Event-driven patterns
