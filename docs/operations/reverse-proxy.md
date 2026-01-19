# Reverse Proxy (Caddy)

Genji Shimada relies on a shared Caddy reverse proxy that also fronts the
monitoring stack and other services. The reverse proxy lives in a separate repo:
[`bkan0n/reverse-proxy`](https://github.com/bkan0n/reverse-proxy). This page explains how it connects to Genji Shimada and
which environment variables are required.

## How It Fits Together

The reverse proxy runs on the same Docker host and attaches to multiple external
networks so it can route traffic to:

- **Genji services** on `genji-network`
- **Monitoring stack** on `caddy-network`
- Other stacks (bkan0n, doom, etc.)

This means the Genji API, RabbitMQ UI, and monitoring endpoints are reachable
through the same proxy and share TLS automation via Cloudflare DNS.

## Genji Routes

From `Caddyfile`:

- `api.genji.pk` -> `genjishimada-api:8000`
- `dev-api.genji.pk` -> `genjishimada-api-dev:8000`
- `rabbitmq.genji.pk` -> `genjishimada-rabbitmq:15672`
- `dev-rabbitmq.genji.pk` -> `genjishimada-rabbitmq-dev:15672`
- `genji.pk` / `dev.genji.pk` -> web containers
- `db.genji.pk` -> `visualdb:80`

## Monitoring Routes

The reverse proxy exposes the monitoring stack and protects some endpoints with
OAuth2 proxy auth:

- `grafana.bkan0n.com` -> `grafana:3000`
- `prometheus.bkan0n.com` -> `prometheus:9090` (auth)
- `loki.bkan0n.com` -> `loki:3100` (auth)
- `alloy.bkan0n.com` -> `alloy:12345` (auth)
- `cadvisor.bkan0n.com` -> `cadvisor:8080` (auth)
- `auth.bkan0n.com` -> `oauth2-proxy:4180`
- `portal.bkan0n.com` -> `keycloak:8080`

Keycloak is already wired through the proxy for auth-related services.

## Required Environment Variables

These env vars are used by the reverse proxy for Cloudflare DNS-01 TLS
automation. They are required for Caddy to issue and renew certificates:

- `BKAN0N_COM_CF_API_TOKEN` - Certificates for `bkan0n.com` and subdomains.
- `GENJI_PK_CF_API_TOKEN` - Certificates for `genji.pk` and subdomains.
- `YOUNGNEBULA_COM_CF_API_TOKEN` - Certificates for `youngnebula.com`.
- `DOOM_PK_CF_API_TOKEN` - Certificates for `doom.pk`.
- `FROMSKYTOCENTER_COM_CF_API_TOKEN` - Certificates for `fromskytocenter.com`.
- `WAITFORMEIN_SPACE_CF_API_TOKEN` - Certificates for `waitformein.space`.

## Genji Service Environment Notes

These Genji services are routed through the proxy and need to be reachable on
the `genji-network`:

- API container (`genjishimada-api` / `genjishimada-api-dev`)
- RabbitMQ management UI (`genjishimada-rabbitmq` / `genjishimada-rabbitmq-dev`)
- Web container (`genjishimada-web` / `genjishimada-web-dev`)

If you change service names or ports in your compose files, update the
`Caddyfile` routes accordingly.

## Related Docs

- [Monitoring](monitoring.md) - Grafana Alloy stack details
- [Docker Compose](docker-compose.md) - Genji service deployment
