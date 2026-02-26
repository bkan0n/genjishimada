# Genji Shimada

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Discord bot and REST API for the Genji Parkour community. Built as a Python monorepo with asynchronous architecture using Litestar, Discord.py, PostgreSQL, and RabbitMQ.

**[Documentation](https://docs.genji.pk)** • **[Community Discord](https://dsc.gg/genjiparkour)** • **[Contributing Guide](CONTRIBUTING.md)**

## What is Genji Shimada?

Genji Shimada powers the Genji Parkour community with:
- **Discord Bot** - Commands, events, and integrations for community management
- **REST API** - Public API for map data, completions, leaderboards, and user profiles
- **Shared SDK** - Type-safe data models using msgspec for communication between services

The bot and API communicate asynchronously via RabbitMQ, enabling reliable event processing and background jobs.

## Quick Start for Contributors

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/), Docker

```bash
# 1. Install dependencies
just setup

# 2. Start infrastructure (PostgreSQL, RabbitMQ, MinIO)
docker compose -f docker-compose.local.yml up -d

# 3. Import database from VPS (requires SSH access)
./scripts/import-db-from-vps.sh dev

# 4. Configure environment
cp .env.local.example .env.local
# Edit .env.local with your Discord token and settings

# 5. Run the bot (or API)
just run-bot
# just run-api
```

**Full setup guide:** See [docs.genji.pk/development/setup](https://docs.genji.pk) for detailed instructions.

## Project Structure

This is a monorepo with three main components:

```
genjishimada/
├── apps/api/          # Litestar REST API with AsyncPG and RabbitMQ
├── apps/bot/          # Discord.py bot with command/event handling
└── libs/sdk/          # Shared msgspec data models and types
```

**Architecture highlights:**
- **API** uses dependency injection pattern with DI modules for business logic
- **Bot** uses extension system with queue consumers for async event processing
- **Message Queue** communication via RabbitMQ with idempotency and DLQ handling
- **Database** PostgreSQL 17 with multiple schemas (core, maps, completions, users, etc.)

Learn more about the architecture at [docs.genji.pk/architecture](https://docs.genji.pk).

## Development Commands

This project uses [just](https://github.com/casey/just) as a task runner.

| Command | Description |
|---------|-------------|
| `just setup` | Install all dependencies (run once) |
| `just sync` | Re-sync dependencies after pulling changes |
| `just run-api` | Start API server (http://localhost:8000) |
| `just run-bot` | Start Discord bot |
| `just lint-api` | Format, lint, and type-check API |
| `just lint-bot` | Format, lint, and type-check bot |
| `just lint-sdk` | Format, lint, and type-check SDK |
| `just lint-all` | Run all linters |
| `just test-api` | Run API tests with pytest |
| `just test-all` | Run all tests |
| `just ci` | Full CI suite (lint + test) |

**Local services when running:**
- API: http://localhost:8000
- API Docs: http://localhost:8000/schema
- RabbitMQ Management: http://localhost:15672 (user: genji, pass: local_dev_password)
- MinIO Console: http://localhost:9001 (user: genji, pass: local_dev_password)

## Contributing

We welcome contributions! Please read our [Contributing Guide](CONTRIBUTING.md) to get started.

**Quick guidelines:**
- Run `just lint-all` and `just test-all` before submitting PRs
- Follow conventional commit format (`feat:`, `fix:`, `docs:`, etc.)
- Add tests for new features and bug fixes
- Check existing issues and PRs before creating new ones

See also:
- [Code of Conduct](.github/CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)

## Technology Stack

**Languages & Frameworks:**
- Python 3.13+ with [uv](https://docs.astral.sh/uv/) package management
- [Litestar](https://litestar.dev/) - Modern async web framework
- [Discord.py](https://discordpy.readthedocs.io/) - Discord API wrapper
- [msgspec](https://jcristharif.com/msgspec/) - Fast serialization library

**Infrastructure:**
- PostgreSQL 17 - Primary database
- RabbitMQ - Message broker for async communication
- MinIO/S3 - Object storage for images
- Docker - Containerization

**Development:**
- Ruff - Linting and formatting
- BasedPyright - Type checking
- pytest - Testing framework
- just - Task runner

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Links

- **Documentation:** https://docs.genji.pk
- **Community Discord:** https://dsc.gg/genjiparkour
- **API Endpoint:** https://api.genji.pk (production)

---

Made with ❤️ for the Genji Parkour community
