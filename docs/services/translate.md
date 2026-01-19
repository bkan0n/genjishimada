# Translate Service

The translate service provides machine translation via LibreTranslate. It is
implemented in the [`genji-infra`](https://github.com/bkan0n/genji-infra) repo
and runs as the `libretranslate` container behind the reverse proxy at
`translate.bkan0n.com`.

## Purpose

LibreTranslate exposes an HTTP API for translating short text and localized
strings used by internal tools.

## Deployment Notes

From `genji-infra`:

- Container: `libretranslate`
- Port: `5000`
- Web UI disabled (`LT_DISABLE_WEB_UI=true`)
- API keys enabled (`LT_API_KEYS=true`)
- Models auto-update (`LT_UPDATE_MODELS=true`)

The reverse proxy routes `translate.bkan0n.com` -> `libretranslate:5000`.

## Configuration

LibreTranslate settings are configured via environment variables in
`genji-infra/libretranslate/libretranslate.env`, including:

- `LT_API_KEYS=true` (requires API keys)
- `LT_REQ_LIMIT=0` (no rate limiting)
- `LT_THREADS=12`
- `LT_FRONTEND_TIMEOUT=2000`

API keys are stored in `/app/db/api_keys.db` via the host volume.

## Related Docs

- [Reverse Proxy](../operations/reverse-proxy.md) - Routing for translate
- [Cloudflare](../operations/cloudflare.md) - DNS entry for translate
