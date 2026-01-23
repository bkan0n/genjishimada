# RabbitMQ Service

RabbitMQ provides message brokering for asynchronous workflows. It enables decoupling between producers and consumers while enforcing delivery guarantees.

## Responsibilities

- Define exchanges, queues, and bindings that reflect business domains.
- Apply dead-lettering and retry policies for resilient processing.
- Monitor queue depth, consumer lag, and connection health.

## Queue naming

Queues follow the pattern: `api.<domain>.<action>`.

Examples:

- `api.completion.submission`
- `api.notification.delivery`
- `api.map_edit.created`

## Access

### Local Development

For local development, RabbitMQ management UI is available at:

```
http://localhost:15672
Username: genji
Password: local_dev_password
```

View logs:
```bash
docker compose -f docker-compose.local.yml logs -f rabbitmq-local
```

### Remote Deployments

RabbitMQ is not exposed directly on remote servers. Production access is handled via your reverse proxy (e.g., Caddy).

View staging logs:
```bash
docker compose -f docker-compose.dev.yml logs -f genjishimada-rabbitmq-dev
```

View production logs:
```bash
docker compose -f docker-compose.prod.yml logs -f genjishimada-rabbitmq
```
