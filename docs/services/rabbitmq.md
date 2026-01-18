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

RabbitMQ is not exposed directly in this repo. Production access is handled via your reverse proxy (e.g., Caddy). For local debugging, use container logs:

```bash
docker compose -f docker-compose.dev.yml logs -f genjishimada-rabbitmq-dev
```
