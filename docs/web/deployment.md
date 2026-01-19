# Deployment

Deployments are handled by GitHub Actions using Docker contexts over SSH. There is one workflow for dev and one for
prod.

## Dev Deployment Workflow

`/.github/workflows/dev-deploy.yml`:

- Triggers:
    - Manual `workflow_dispatch` (with a ref override).
    - PR comment with `.deploy` using `github/branch-deploy`.
- Uses a Docker context over SSH to the dev host.
- Runs `docker compose -f docker-compose.dev.yml up -d --build`.

## Prod Deployment Workflow

`/.github/workflows/prod-deploy.yml`:

- Triggers on `push` to `main` and manual dispatch.
- Uses a Docker context over SSH to the prod host.
- Runs `docker compose -f docker-compose.prod.yml up -d --build`.

## Compose Files

Both compose files:

- Build the same Dockerfile.
- Inject the full environment set from GitHub secrets.
- Attach to the external `genji-network`.

There is no database container defined here. The website uses the same database as the bot and API, and expects that
database to be reachable on the shared network.

## Environment Variables

The workflows pass env vars for:

- Genji API access (`X_API_ROOT`, `X_API_KEY`, `X_API_VERIFY`).
- Discord OAuth + bot (`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`,
  `DISCORD_MODERATOR_ROLE_IDS`).
- OCR + Translation API (`TRANSLATION_API_ROOT`, `TRANSLATION_API_KEY`, `TRANSLATION_API_VERIFY`).
- Sentry (backend + frontend).
- Session settings (`SESSION_SECURE_COOKIE`, `SESSION_DOMAIN`).
