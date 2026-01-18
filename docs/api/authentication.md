# Authentication

The Genji Shimada API uses **API keys** for all authenticated requests. This is the only supported method for service-to-service communication.

## API Keys

**Use case**: Bot, internal services, or trusted backend clients.

API keys are stored in the `public.api_tokens` table and attached to an auth user record.

### Using an API Key

Include the key in the `X-API-KEY` header:

```bash
curl -H "X-API-KEY: your_api_key" \
  https://api.genji.pk/api/v3/maps
```

**Example (Python):**

```python
import httpx

headers = {"X-API-KEY": "your_api_key"}
response = httpx.get("https://api.genji.pk/api/v3/maps", headers=headers)
```

### Scopes

API keys may be scoped. The middleware attaches `scopes` and `is_superuser` to the request auth token.

Common scope examples:

- `read:maps`
- `write:maps`
- `read:users`
- `write:completions`
- `admin:*`

Routes can require scopes via `required_scopes`:

```python
@get(
    "/admin/users",
    opt={"required_scopes": {"admin:users"}},
)
async def list_all_users() -> list[User]:
    ...
```

## Middleware

Authentication is enforced by `CustomAuthenticationMiddleware` in `apps/api/middleware/auth.py`.

### Excluding Routes from Auth

Routes can opt out of authentication with `exclude_from_auth`:

```python
@get("/healthcheck", opt={"exclude_from_auth": True})
async def health_check() -> dict:
    return {"status": "ok"}
```

## Best Practices

- Use **least-privilege** keys for each service.
- Rotate keys periodically.
- Store keys in environment variables, never in code.

## Troubleshooting

### Missing API Key

**Error**: `401 Unauthorized - Missing API key`

**Solution**: Ensure `X-API-KEY` is present on the request.

### Invalid API Key

**Error**: `401 Unauthorized - Invalid API key`

**Solution**: Verify the key is correct and active.

### Insufficient Permissions

**Error**: `403 Forbidden - Missing required scopes: ...`

**Solution**: Update the key's scopes or use a superuser token.

## Next Steps

- [OpenAPI Reference](openapi.md) - Review endpoint auth requirements
- [External API Docs](https://api.genji.pk/docs) - Interactive Swagger UI
