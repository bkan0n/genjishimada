# API Documentation

The Genji Shimada API is a **Litestar-based REST API** for maps, completions, user profiles, authentication, and related services.

## Overview

The API is built with:

- **Litestar** - Modern, fast Python web framework
- **AsyncPG** - High-performance PostgreSQL driver
- **msgspec** - Fast JSON serialization
- **PostgreSQL queue** - Asynchronous message passing to the bot

## Base URLs

The API is served under the `/api/v3` prefix.

- **Production**: `https://api.genji.pk/api/v3`
- **Development**: `https://dev-api.genji.pk/api/v3`
- **Local**: `http://localhost:8000/api/v3`

## Quick Links

<div class="grid cards" markdown>

-   :material-file-document:{ .lg .middle } **OpenAPI Reference**

    ---

    Browse the complete API specification

    [:octicons-arrow-right-24: OpenAPI Spec](openapi.md)

-   :material-shield-lock:{ .lg .middle } **Authentication**

    ---

    Learn how API keys and scopes work

    [:octicons-arrow-right-24: Auth Guide](authentication.md)

-   :material-link-variant:{ .lg .middle } **External API Docs**

    ---

    Interactive Swagger UI hosted on the API server

    [:octicons-arrow-right-24: api.genji.pk/docs](https://api.genji.pk/docs){ target="_blank" }

</div>

## Key Features

### RESTful Endpoints

Example endpoints (all under `/api/v3`):

- `GET /maps` - List and search maps
- `POST /completions` - Submit a completion
- `GET /users/{user_id}` - Get user profile
- `PUT /users/{user_id}/settings` - Update user settings

### Authentication

All endpoints require an API key unless explicitly excluded. See the [Authentication Guide](authentication.md).

### Message Queue Integration

The API publishes events to the PostgreSQL queue for asynchronous processing by the bot:

```
API → PostgreSQL queue → Bot
```

Examples:
- Completion submissions trigger Discord notifications
- Map updates notify subscribers
- User achievements are announced in channels

### Database Architecture

The API uses **PostgreSQL 17** with multiple schemas:

- `core.*` - Users, maps, permissions
- `maps.*` - Map metadata and ratings
- `completions.*` - User completion records
- `users.*` - Profiles and XP

Migrations are located in `apps/api/migrations/`.

## Development

### Running Locally

```bash
just run-api
```

The API starts at `http://localhost:8000` with hot reload enabled.

### Interactive Docs

Visit `http://localhost:8000/docs` for the Swagger UI.

### Testing

Run the test suite:

```bash
just test-api
just test-queue
```

The feature-organized API suite uses two workers by default. Queue acceptance runs separately and serially with disposable PostgreSQL instances, including process and database recovery tests. See [API test instructions](https://github.com/bkan0n/genjishimada/blob/main/apps/api/README.md) for order, worker, and feature selection options.

## Architecture Highlights

### Dependency Injection Pattern

Business logic is separated from HTTP routing:

- **`apps/api/di/*.py`** - DI modules with business logic
- **`apps/api/routes/*.py`** - Thin HTTP handlers

Example flow:

1. Route handler receives request
2. Validates parameters
3. Calls DI function with database connection
4. DI function performs business logic
5. Returns serialized response

### Idempotency

Queue operations use durable event identities and per-effect receipts. Replaying a job preserves completed effects; a claim alone never proves completion.

### Error Handling

Custom exceptions in `utilities/errors.py` provide structured error responses:

```python
from utilities.errors import CustomHTTPException

raise CustomHTTPException(
    status_code=404,
    detail="Map not found",
)
```

## Next Steps

- [OpenAPI Reference](openapi.md) - Full API specification
- [Authentication](authentication.md) - API key usage and scopes
- [Architecture](architecture.md) - Code structure and patterns
- [Local Development](local-development.md) - Run the API locally
- [Deployment](deployment.md) - Running in production
