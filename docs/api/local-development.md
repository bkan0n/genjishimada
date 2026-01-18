# Local Development

How to run the API locally for development and testing.

## Prerequisites

- Docker and Docker Compose
- Python 3.13+
- `uv` and `just`

## Environment variables

Create a `.env` file at the repo root with at least:

```env
APP_ENVIRONMENT=development
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=your_password
POSTGRES_DB=genjishimada
RABBITMQ_USER=admin
RABBITMQ_PASS=your_password
RABBITMQ_HOST=localhost
API_KEY=your_api_key_for_bot
```

If you are running the API **in Docker**, set `RABBITMQ_HOST=genjishimada-rabbitmq-dev`.

If you are running the API **on the host**, set `PSQL_DSN` so it points at the mapped Postgres port:

```env
PSQL_DSN=postgresql://genjishimada:your_password@localhost:65432/genjishimada
```

Add any optional values you need (Sentry, R2, Resend).

## Start infrastructure

Start the database and RabbitMQ only:

```bash
docker compose -f docker-compose.dev.yml up -d \
  genjishimada-db-dev \
  genjishimada-rabbitmq-dev
```

## Run the API on the host

```bash
just run-api
```

The API starts at `http://localhost:8000`.

### Health check

```bash
curl http://localhost:8000/healthcheck
```

### Swagger UI

Open `http://localhost:8000/docs`.

## Run the API in Docker (optional)

If you want Docker to run everything, use the compose service:

```bash
docker compose -f docker-compose.dev.yml up -d genjishimada-api-dev
```

This expects the same `.env` variables.

## Troubleshooting

- **Database connection errors**: confirm `genjishimada-db-dev` is healthy.
- **RabbitMQ connection errors**: confirm `genjishimada-rabbitmq-dev` is healthy.

## Next Steps

- [OpenAPI Reference](openapi.md)
- [Authentication](authentication.md)
