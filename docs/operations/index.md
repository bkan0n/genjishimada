# Operations

Guides for deploying, configuring, and maintaining Genji Shimada in production and development environments.

## Overview

This section covers:

- **Infrastructure** - PostgreSQL, RabbitMQ, and cloud services
- **Docker Compose** - Local and production deployments
- **Configuration** - Environment variables and config files
- **Reverse Proxy** - Caddy routing, domains, and TLS
- **Identity & Auth** - Keycloak and oauth2-proxy
- **Cloudflare** - DNS and CDN configuration
- **Monitoring** - Grafana Alloy stack and dashboards

## Quick Links

<div class="grid cards" markdown>

-   :material-server:{ .lg .middle } **Infrastructure**

    ---

    Learn about the services that power Genji Shimada

    [:octicons-arrow-right-24: Infrastructure Guide](infrastructure.md)

-   :material-docker:{ .lg .middle } **Docker Compose**

    ---

    Deploy with Docker for development and production

    [:octicons-arrow-right-24: Docker Guide](docker-compose.md)

-   :material-shield-lock:{ .lg .middle } **Reverse Proxy**

    ---

    Caddy routing and Cloudflare TLS automation

    [:octicons-arrow-right-24: Reverse Proxy Guide](reverse-proxy.md)

-   :material-monitor-dashboard:{ .lg .middle } **Monitoring**

    ---

    Set up Grafana Alloy, dashboards, and log collection

    [:octicons-arrow-right-24: Monitoring Guide](monitoring.md)

-   :material-account-key:{ .lg .middle } **Identity & Auth**

    ---

    Keycloak and oauth2-proxy configuration

    [:octicons-arrow-right-24: Identity & Auth Guide](identity-and-auth.md)

-   :material-cloud:{ .lg .middle } **Cloudflare**

    ---

    DNS, CDN, and R2 configuration

    [:octicons-arrow-right-24: Cloudflare Guide](cloudflare.md)

</div>

## Environment Configuration

Create a `.env` file in the repo root with the variables required by your services. At minimum:

```env
APP_ENVIRONMENT=development
DISCORD_TOKEN=your_bot_token
POSTGRES_USER=genjishimada
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=genjishimada
RABBITMQ_USER=admin
RABBITMQ_PASS=secure_password
RABBITMQ_HOST=localhost
API_KEY=secure_api_key_for_bot
```

Add optional values for Sentry, R2, and Resend as needed.

If you run the API/bot in Docker, set `RABBITMQ_HOST` to the service name (`genjishimada-rabbitmq-dev` or `genjishimada-rabbitmq`).

## Health Checks

### API Health Check

```bash
curl http://localhost:8000/healthcheck
```

If the API runs in Docker without a port mapping, access it through your reverse proxy instead.

### Database Health

```bash
docker compose -f docker-compose.dev.yml exec genjishimada-db-dev pg_isready
```

### RabbitMQ Health

RabbitMQ is not exposed directly in this repo; use container logs or your reverse proxy setup.

## Next Steps

- [Infrastructure Details](infrastructure.md) - Deep dive into services
- [Docker Compose Guide](docker-compose.md) - Deployment strategies
- [Bot Configuration](../bot/operations/configuration.md) - Bot-specific config
