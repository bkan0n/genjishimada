# Genji Shimada

Welcome to the official documentation for **Genji Shimada**, the Discord bot and REST API powering the Genji Parkour community.

## What is Genji Shimada?

Genji Shimada is a comprehensive platform built with Python 3.13+ that provides:

- **Discord Bot** - Interactive Discord bot for community engagement, completions tracking, and notifications
- **REST API** - Litestar-based API for maps, completions, user profiles, and more
- **Shared SDK** - Type-safe msgspec data models shared across all services

## Quick Links

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting Started**

    ---

    Install dependencies and run the bot or API locally in minutes

    [:octicons-arrow-right-24: Get Started](getting-started/index.md)

-   :fontawesome-brands-discord:{ .lg .middle } **Bot Documentation**

    ---

    Learn about the bot's architecture, extensions, and queue consumers

    [:octicons-arrow-right-24: Explore Bot](bot/index.md)

-   :material-api:{ .lg .middle } **API Reference**

    ---

    Browse the OpenAPI specification and authentication guides

    [:octicons-arrow-right-24: API Docs](api/index.md)

-   :material-package-variant:{ .lg .middle } **SDK**

    ---

    Understand the shared data models and types

    [:octicons-arrow-right-24: SDK Guide](sdk/index.md)

</div>

## Architecture Overview

The project is structured as a **monorepo** with three main components:

```
genjishimada/
├── apps/
│   ├── api/          # Litestar REST API
│   └── bot/          # Discord.py bot
└── libs/
    └── sdk/          # Shared msgspec models
```

### Key Technologies

- **Python 3.13+** with uv for package management
- **Litestar** for the REST API
- **Discord.py** for the Discord bot
- **PostgreSQL 17** for data persistence
- **RabbitMQ** for async message passing
- **msgspec** for fast, type-safe serialization

## Community

- **Discord Server**: [discord.gg/genji](https://discord.gg/genji)
- **GitHub**: [bkan0n/genjishimada](https://github.com/bkan0n/genjishimada)
- **Production API**: [api.genji.pk](https://api.genji.pk)

## Contributing

Contributions are welcome! Check out the [Contributing Guide](contributing/index.md) to get started.
