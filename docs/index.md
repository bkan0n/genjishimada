# Genji Shimada

This documentation explains how the Genji Shimada bot, API, SDK, website, and infrastructure work together.

## What this is for

Genji Parkour is a custom Overwatch game mode built in Workshop. The framework for the mode lives in
[`tylovejoy/genji-framework`](https://github.com/tylovejoy/genji-framework), and the Workshop code to play it is
`54CRY`.

The Genji Shimada system supports the community workflow around that mode:

- Players submit maps for playtesting and difficulty review.
- Approved maps are published so players can submit completion times.
- Records, XP, and rank cards are tracked and displayed for users.
- Newsfeed, statistics, and moderation tooling keep the community and map pipeline moving.

The system also covers:

- Map search, guides, and edit requests.
- Community leaderboards and statistics dashboards.
- Lootbox rewards and XP tuning workflows.
- OCR-assisted completion submissions.
- Translations for UI and newsfeed content.

## What is in this repo

- **Discord Bot** — Discord automation and event handling.
- **REST API** — Litestar API for maps, completions, users, and moderation workflows.
- **SDK** — Shared models and client types used by services and tooling.
- **Docs for the website** — The website code lives in [`bkan0n/genji.pk`](https://github.com/bkan0n/genji.pk).

## Quick Links

<div class="grid cards" markdown>

- :material-rocket-launch:{ .lg .middle } **Getting Started**

  ---

  Install dependencies and run the bot or API locally

  [:octicons-arrow-right-24: Get Started](getting-started/index.md)

- :fontawesome-brands-discord:{ .lg .middle } **Bot Documentation**

  ---

  Bot architecture, extensions, and queue consumers

  [:octicons-arrow-right-24: Explore Bot](bot/index.md)

- :material-api:{ .lg .middle } **API Reference**

  ---

  OpenAPI spec, auth, and endpoints

  [:octicons-arrow-right-24: API Docs](api/index.md)

- :material-package-variant:{ .lg .middle } **SDK**

  ---

  SDK usage and generated model reference

  [:octicons-arrow-right-24: SDK Guide](sdk/index.md)

</div>

## Repository layout

The project is a monorepo with three main components:

```
genjishimada/
├── apps/
│   ├── api/          # Litestar REST API
│   └── bot/          # Discord.py bot
└── libs/
    └── sdk/          # Shared msgspec models
```

### Key technologies

- **Python 3.13+** with uv for package management
- **Litestar** for the REST API
- **Discord.py** for the Discord bot
- **PostgreSQL 17** for data persistence
- **RabbitMQ** for async message passing
- **msgspec** for fast serialization and validation

## Community

- **Discord Server**: [dsc.gg/genjiparkour](https://dsc.gg/genjiparkour)
- **GitHub**: [bkan0n/genjishimada](https://github.com/bkan0n/genjishimada)
- **Production API**: [api.genji.pk](https://api.genji.pk)

## Contributing

See the [Contributing Guide](contributing/index.md) if you want to help or test changes locally.
