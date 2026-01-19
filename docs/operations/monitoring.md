# Monitoring

Genji Shimada uses a Grafana Alloy-based monitoring stack in a separate repo:
[`genjishimada-monitoring`](https://github.com/bkan0n/genjishimada-monitoring). It collects metrics and logs from the host and
Docker containers, stores metrics in Prometheus and logs in Loki, and exposes
dashboards through Grafana.

## What It Includes

- **Grafana Alloy** for metrics and log collection.
- **Prometheus** for metrics storage and queries.
- **Loki** for log storage and queries.
- **cAdvisor** for Docker container metrics.
- **Grafana** dashboards and alerting UI.

## Setup (Brief)

1. Clone the monitoring repo on the server:

```bash
git clone https://github.com/bkan0n/genjishimada-monitoring.git
cd genjishimada-monitoring
```

2. Create the external network for your reverse proxy (Caddy):

```bash
docker network create caddy-network
```

3. Copy and edit the env file:

```bash
cp .env.example .env
```

Set:
- `HOSTNAME` to your server hostname (used as a label in metrics/logs).
- `GRAFANA_ADMIN_PASSWORD` to a strong password.
- `TZ` if you want consistent dashboard timestamps.

4. Start the stack:

```bash
docker compose up -d
```

## Grafana Access and Auth

Grafana is configured for Keycloak OAuth in
`config/grafana/grafana.ini`. If you are not using the same Keycloak domain,
update the `auth.generic_oauth` section (client id, URLs, and redirect targets),
or disable OAuth and use basic auth.

By default, Grafana listens on port 3000. If you front it with Caddy, route the
public domain to the `grafana` service on the `caddy-network`.

## What to Expect

- **Dashboards** are auto-provisioned from `dashboards/`:
  - Docker Containers (CPU, memory, network, tables)
  - Host System Metrics (CPU, memory, disk, network)
  - Logs Explorer (container logs + journald + host logs)
- **Datasources** are pre-provisioned:
  - Prometheus at `http://prometheus:9090`
  - Loki at `http://loki:3100`
- **Log sources** include Docker containers, systemd journal, and `/var/log`.
- **Alloy UI** is available at `http://localhost:12345` for debugging.

## Notes

- Alloy runs with elevated permissions and mounts host paths for metrics/logs.
- If you are not running a reverse proxy, Grafana is still reachable at
  `http://localhost:3000` on the host.
