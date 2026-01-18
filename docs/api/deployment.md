# Deployment

This project deploys the API with Docker Compose. The exact deployment workflow (CI/CD, SSH, etc.) depends on your environment.

## Production compose

The production compose file defines these services:

- `genjishimada-api`
- `genjishimada-bot`
- `genjishimada-db`
- `genjishimada-rabbitmq`

Start them with:

```bash
docker compose -f docker-compose.prod.yml up -d
```

## Environment variables

Create a production `.env` with the values required by the API and bot:

```env
APP_ENVIRONMENT=production
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=your_password
POSTGRES_DB=genjishimada
RABBITMQ_USER=admin
RABBITMQ_PASS=your_password
RABBITMQ_HOST=genjishimada-rabbitmq
API_KEY=your_api_key_for_bot
```

Add any optional values (Sentry, R2, Resend) as needed.

## Health checks

The API service includes a health check at `/healthcheck`. Within Docker, this runs on `http://localhost:8000/healthcheck` inside the container. Expose it through your reverse proxy if you need external access.

## Logs

```bash
docker compose -f docker-compose.prod.yml logs -f genjishimada-api
```

## Notes

RabbitMQ and Postgres are attached to the external `genji-network`. Ensure that network exists in your environment.
