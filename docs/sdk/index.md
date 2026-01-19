# SDK Documentation

The **Genji Shimada SDK** ([`genjishimada-sdk`](https://github.com/bkan0n/genjishimada-sdk)) is a shared library containing msgspec Struct definitions used across the API and bot.

## Overview

The SDK provides:

- **Type-safe data models** using msgspec
- **Shared validation logic** between services
- **Fast serialization/deserialization** with msgspec
- **IDE auto-completion** for all data structures

## Package Structure

```
libs/sdk/
├── src/
│   └── genjishimada_sdk/
│       ├── __init__.py
│       ├── maps.py          # Map-related models
│       ├── completions.py   # Completion models
│       ├── users.py         # User profile models
│       ├── notifications.py # Notification models
│       ├── lootbox.py       # Lootbox models
│       └── ...
└── pyproject.toml
```

## Why msgspec?

The SDK uses [msgspec](https://jcristharif.com/msgspec/) instead of Pydantic for several reasons:

- **Performance** - Fast serialization
- **Smaller memory footprint** - Efficient encoding
- **Type safety** - Strict validation at runtime
- **Minimal overhead** - Lightweight dependency graph

## Installation

The SDK is installed automatically when you run:

```bash
just setup
```

## Quick Example

```python
import msgspec
from genjishimada_sdk.users import UserCreateRequest

payload = UserCreateRequest(
    id=1234567890,
    global_name="Player",
    nickname="Player",
)

json_bytes = msgspec.json.encode(payload)
```

## Next Steps

- [SDK Reference](reference/index.md) - Auto-generated API docs
- [Data Models](data-models.md) - Module overview
- [Usage Examples](usage.md) - Common patterns and recipes
- [API Documentation](../api/index.md) - See how the API uses the SDK
- [Bot Architecture](../bot/architecture/messaging.md) - Learn about message queue integration
