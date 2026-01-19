# Cloudflare (DNS + CDN)

Genji Shimada uses Cloudflare for DNS, TLS, and CDN delivery. This page captures
the relevant records and R2/CDN settings used by the stack.

## Zones

- `bkan0n.com`
- `genji.pk`

Both zones are proxied through Cloudflare. The origin IP is intentionally
omitted from docs; store it in your private ops notes.

## DNS Records (Relevant Only)

Only records used by Genji Shimada and related infrastructure are listed below.

### bkan0n.com

- `bkan0n.com` (A, proxied) -> origin IP (private)
- `auth.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `portal.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `grafana.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `prometheus.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `loki.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `alloy.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `cadvisor.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `status.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `translate.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `dockhand.bkan0n.com` (CNAME, proxied) -> `bkan0n.com`
- `cdn.bkan0n.com` (CNAME, proxied) -> `public.r2.dev`

### genji.pk

- `genji.pk` (A, proxied) -> origin IP (private)
- `api.genji.pk` (CNAME, proxied) -> `genji.pk`
- `dev-api.genji.pk` (CNAME, proxied) -> `genji.pk`
- `dev.genji.pk` (CNAME, proxied) -> `genji.pk`
- `rabbitmq.genji.pk` (CNAME, proxied) -> `genji.pk`
- `dev-rabbitmq.genji.pk` (CNAME, proxied) -> `genji.pk`
- `db.genji.pk` (CNAME, proxied) -> `genji.pk`
- `docs.genji.pk` (CNAME, proxied) -> `genjishimada.github.io`
- `cdn.genji.pk` (CNAME, proxied) -> `public.r2.dev`

## SSL/TLS

- **Mode:** Full

## R2 Buckets and CDN

Public CDN domains:

- `cdn.bkan0n.com`
- `cdn.genji.pk`

Buckets in use:

- `genji-db-backups`
- `genji-parkour-images`

### R2 CORS Policy

Allowed origins:

- `http://genji.test`
- `https://dev.genji.pk`
- `https://genji.pk`
- `http://localhost:3000`

Allowed methods: `GET`, `HEAD`  
Allowed headers: `*`

### R2 Response Headers

For wildcard hostnames `*.bkan0n.com` and `*.genji.pk`:

- `Cross-Origin-Resource-Policy: cross-origin`
- `Vary: Origin, Access-Control-Request-Method, Access-Control-Request-Headers`

## Related Docs

- [Reverse Proxy](reverse-proxy.md) - Caddy routing and TLS automation
- [Monitoring](monitoring.md) - Grafana/Prometheus/Loki endpoints
