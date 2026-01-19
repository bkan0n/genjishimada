# Website Overview

The Genji website code lives in https://github.com/bkan0n/genji.pk and serves the public site at `genji.pk` (with `dev.genji.pk` for development). This section documents how the Laravel app is structured, built, and deployed, plus how it connects to the rest of the Genji stack.

## Key Facts

- Laravel app served by Nginx Unit (`serversideup/php:8.3-unit`).
- Uses the same database as the bot and API, and relies on the Genji API for auth and session data.
- Frontend built with Vite and Tailwind, with per-page JS bundles.
- Integrates Discord OAuth, OCR, Translation API, Tenor GIFs, Sentry, and GitHub releases.

## Pages In This Section

- [Repository Layout](repository-layout.md)
- [Runtime Container](runtime-container.md)
- [Deployment](deployment.md)
- [Frontend Build](frontend.md)
- [Backend Application](backend.md)
- [Integrations](integrations.md)
- [Security And Sessions](security-and-sessions.md)
- [Localization And Translations](localization.md)
