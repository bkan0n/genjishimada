# Integrations

This site relies on several external services configured in `config/services.php` and related config files.

## Genji API

- Config: `services.genji_api` (from `X_API_ROOT`, `X_API_KEY`, `X_API_VERIFY`).
- Used for user and session operations (login, registration, remember token, session I/O).
- See `App\Services\GenjiApiService` and `App\Extensions\ApiSessionHandler`.

## Discord OAuth + Bot

- Socialite provider registered in `AppServiceProvider`.
- OAuth endpoints used for user sign-in.
- Bot token and guild info are used to hydrate avatars and moderator roles.

## OCR Service

- `services.ocr.base_url` resolves by environment.
- `/api/ocr/extract` proxies OCR requests.

## Translation Service

- `services.translation_api` provides translation endpoint and API key.
- Used by the newsfeed translation flow.

## Tenor GIFs

- `TENOR_API_KEY` enables GIF lookup in newsfeed.

## GitHub Releases

- `App\Services\GitHubReleases` fetches releases for the Genji framework.
- Repo defaults to `tylovejoy/genji-framework` unless configured.

## Sentry

- Backend Sentry configured in `config/sentry.php`.
- Frontend Sentry initialized in `resources/js/app.js`.
- Sentry tunnel endpoint exists at `/api/_/e` and validates the DSN.

## Cloudflare Integration

- `config/laravelcloudflare.php` enables middleware for Cloudflare IPs.
- `routes/web.php` includes `/api/my-ip` for debugging forwarded IPs.

## CDN Helpers

- `cdn_asset()` uses `config('app.cdn_url')` (default `https://cdn.genji.pk`).

## Optional Email Providers

Mailgun, Postmark, and SES are configured in `config/services.php`, but usage depends on environment setup.

## Unused Reserved Env Vars

`BATTLENET_CLIENT_ID` and `BATTLENET_CLIENT_SECRET` are present in compose files but are not referenced in the codebase.
