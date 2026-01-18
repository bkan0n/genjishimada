# Domain Overview

Genji Shimada orchestrates messaging, automation, and content workflows across multiple services. Each service is scoped to a clear responsibility, while shared practices such as deployment and configuration keep the system consistent.

## Architecture Snapshot

- **Bot**: Orchestrates interactions with Discord and routes user intents.
- **API**: Exposes HTTP interfaces for clients and internal consumers.
- **Database**: Persists application and operational data.
- **RabbitMQ**: Coordinates asynchronous tasks and event delivery between services.
- **OCR**: Extracts structured data from parkour screenshots for downstream automation.

## Operational Practices

- Environment-specific configuration for development vs production.
- Health checks to validate deployments.
- Centralized logging and error tracking.
