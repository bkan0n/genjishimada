# Runtime Container

The container is built in three stages and runs on Nginx Unit.

## Multi-Stage Build

1) Node build
- Uses `node:20-alpine`.
- Runs `npm ci` and `npm run build` to generate `public/build`.

2) Composer dependencies
- Uses `composer:2` to install PHP deps without dev scripts.

3) Runtime
- Uses `serversideup/php:8.3-unit`.
- Copies app code, `vendor/`, and `public/build`.
- Configures opcache and memory limits.
- Ensures `storage/` and `bootstrap/cache` permissions.

## Unit Configuration

`docker/unit.json`:
- Listens on `*:8080`.
- Serves static assets from `public/` with long-lived cache headers.
- Falls back to `index.php` for dynamic routes.
- Sets PHP process limits and upload size caps.

## Entrypoint Flow

`docker/entrypoint.sh`:
- Fixes permissions for runtime write paths.
- Starts Unit and waits for the control socket.
- Loads Unit config via the control API.
- Optionally warms caches (`package:discover`, `optimize`, `event:cache`, `route:cache`, `view:cache`).

## Healthcheck

The Dockerfile defines a healthcheck against `http://localhost:8080`.
