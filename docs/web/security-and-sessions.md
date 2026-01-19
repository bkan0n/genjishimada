# Security And Sessions

This app uses a mix of Laravel defaults and platform-specific session handling.

## API-Backed Sessions

- `config/session.php` sets the driver to `api` and enables encryption.
- `ApiSessionHandler` stores session data via the Genji API.
- Remember-token flows use `device_session_id` cookies to keep sessions consistent across devices.

## Auth And Role Checks

- Discord moderator access is enforced in `RequireDiscordModerator`.
- Email users are still supported through the Genji API endpoints.

## CSRF

`resources/js/app.js` patches `fetch()` to attach `X-CSRF-TOKEN` and `X-Requested-With` headers on non-GET requests.

## CSP And Nonce

- `config/csp.php` defines a strict CSP and uses a nonce generator.
- `AppServiceProvider` wires a CSP nonce into Vite via `Vite::useCspNonce()`.

## Sentry Tunnel

- `/api/_/e` validates DSN headers and same-site origin before forwarding.
- Size limits are enforced to avoid oversized payloads.

## Cookies And Domains

- Session cookie domain and HTTPS requirements are controlled by `SESSION_DOMAIN` and `SESSION_SECURE_COOKIE`.
- SameSite is set to `lax` by default.
