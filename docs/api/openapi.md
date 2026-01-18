# OpenAPI Reference

The complete OpenAPI specification for the Genji Shimada API.

!!! info "Generated Specification"
This page contains the **authoritative** OpenAPI spec, generated directly from the Litestar application.

## Interactive Documentation

For a more interactive experience with request/response testing, visit:

- **Production**: [https://api.genji.pk/docs](https://api.genji.pk/docs)
- **Development**: [https://dev-api.genji.pk/docs](https://dev-api.genji.pk/docs)

!!! tip "Download Spec"
You can download the raw OpenAPI spec in JSON format: [openapi.json](../openapi.json)

## Generating the Spec Locally

To regenerate the OpenAPI spec from the Litestar app:

```bash
uv run --project apps/api python scripts/generate_openapi.py
```

To build the documentation site afterward:

```bash
uv run --project docs mkdocs build
```

## Using the Spec

### Import into Postman

1. Download [openapi.json](../openapi.json)
2. Open Postman
3. Click **Import** → **Upload Files**
4. Select the downloaded `openapi.json`

### Generate Client SDKs

Use tools like [openapi-generator](https://openapi-generator.tech/) to generate client libraries:

```bash
openapi-generator-cli generate \
  -i docs/openapi.json \
  -g python \
  -o ./generated-client
```

### Validate Requests

Use the spec to validate API requests in your tests or CI/CD pipeline.

## Specification Details

The OpenAPI spec includes:

- **All endpoints** with request/response schemas
- **Authentication** requirements (API key and scopes)
- **Error responses** with status codes and messages
- **Data models** for all request and response bodies

## Schema Highlights

### Authentication

The spec documents API key authentication via the `X-API-KEY` header.

### Endpoints

Major endpoint groups:

- `/maps` - Map CRUD and search
- `/completions` - Completion submissions and tracking
- `/users` - User profiles and settings
- `/auth` - Email-based authentication endpoints
- `/notifications` - Notification delivery
- `/lootbox` - Lootbox system

### Models

All request/response bodies use msgspec Struct definitions from `libs/sdk`.

## Next Steps

- [Authentication Guide](authentication.md) - Learn how to authenticate API requests
- [External API Docs](https://api.genji.pk/docs) - Try the API interactively
