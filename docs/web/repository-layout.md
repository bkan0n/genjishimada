# Repository Layout

This repo follows a standard Laravel structure with a few custom additions for Genji.

## Top-Level Structure

- `app/` - Application code.
  - `Http/Controllers` grouped by domain (Maps, Newsfeed, Lootbox, Mods, Users, Utilities).
  - `Http/Middleware` for auth, Discord moderation, locale detection, Sentry user context.
  - `Services` for Genji API and GitHub releases.
  - `Extensions/ApiSessionHandler` for API-backed sessions.
  - `Support` helpers and translation utilities.
  - `Providers` register services and middleware.
- `routes/` - `web.php` pages and auth flows, `api.php` JSON endpoints, `console.php` for CLI hooks.
- `resources/` - Blade views, JS, CSS, and language assets.
- `public/` - Public assets and `public/build` output from Vite.
- `config/` - App, services, CSP, sessions, Cloudflare middleware, Sentry, and custom settings.
- `docker/` - Unit config and entrypoint.
- `docker-compose.dev.yml` / `docker-compose.prod.yml` - Deployment entrypoints.
- `Dockerfile` - Multi-stage build for frontend assets and PHP runtime.
- `.github/workflows/` - Dev and prod deploy workflows.

## Important Files

- `Dockerfile` - Node build, Composer install, then Unit runtime image.
- `docker/unit.json` - Unit routes, static caching, and PHP process settings.
- `docker/entrypoint.sh` - Unit bootstrap and cache warming.
- `vite.config.js` - Vite input bundles for each page.
- `tailwind.config.js` - Theme, colors, and animation settings.
