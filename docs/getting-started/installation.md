# Installation

Detailed installation instructions for Genji Shimada.

!!! note
    If you haven't already, review the [Getting Started Overview](index.md) for prerequisites and initial setup steps.

## System Requirements

### Minimum Requirements

- **CPU**: 2 cores
- **RAM**: 4 GB
- **Disk**: 5 GB free space
- **OS**: Linux, macOS, or Windows with WSL2

### Recommended for Development

- **CPU**: 4+ cores
- **RAM**: 8+ GB
- **Disk**: 10+ GB free space (for Docker images and databases)

## Step-by-Step Installation

### 1. Install Python 3.13+

=== "macOS"

    Using Homebrew:
    ```bash
    brew install python@3.13
    ```

=== "Linux (Ubuntu/Debian)"

    ```bash
    sudo apt update
    sudo apt install python3.13 python3.13-venv python3.13-dev
    ```

=== "Windows"

    Download from [python.org](https://www.python.org/downloads/) and run the installer.

    Ensure "Add Python to PATH" is checked during installation.

Verify installation:

```bash
python3.13 --version
```

### 2. Install uv

The project uses `uv` for fast dependency management:

=== "macOS/Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    ```powershell
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Verify installation:

```bash
uv --version
```

### 3. Install just

`just` is used as a task runner for common development commands:

=== "macOS"

    ```bash
    brew install just
    ```

=== "Linux"

    ```bash
    cargo install just
    ```

    Or download from [GitHub releases](https://github.com/casey/just/releases).

=== "Windows"

    ```powershell
    cargo install just
    ```

Verify installation:

```bash
just --version
```

### 4. Install Docker

Docker is required for running PostgreSQL and RabbitMQ:

- **macOS**: [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
- **Linux**: [Docker Engine](https://docs.docker.com/engine/install/)
- **Windows**: [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)

Verify installation:

```bash
docker --version
docker compose version
```

### 5. Clone the Repository

```bash
git clone https://github.com/bkan0n/genjishimada.git
cd genjishimada
```

### 6. Install Project Dependencies

Run the setup command to install all dependencies:

```bash
just setup
```

This command:
1. Creates virtual environments for all workspaces
2. Installs Python dependencies
3. Sets up development tools (Ruff, BasedPyright, pytest)

### 7. Configure Local Environment

Copy the local environment template:

```bash
cp .env.local.example .env.local
```

Edit `.env.local` with your Discord bot token and other settings. The database, RabbitMQ, and MinIO settings are pre-configured for local development.

### 8. Start Local Infrastructure

Start PostgreSQL, RabbitMQ, and MinIO for local development:

```bash
docker compose -f docker-compose.local.yml up -d
```

Check that services are healthy:

```bash
docker compose -f docker-compose.local.yml ps
```

All services should show status "Up (healthy)".

### 9. Create MinIO Bucket

Create the S3 bucket in MinIO for image storage:

```bash
# Install MinIO client
brew install minio/stable/mc  # macOS/Linux

# Configure and create bucket
mc alias set local http://localhost:9000 genji local_dev_password
mc mb local/genji-parkour-images
```

### 10. Import Database (Optional)

To work with real data, import from the VPS:

```bash
./scripts/import-db-from-vps.sh dev
```

This requires SSH access to the VPS. See [Getting Started](index.md#ssh-configuration) for SSH configuration.

## Verification

Verify your installation by running the linters:

```bash
just lint-all
```

All checks should pass (or report only pre-existing issues).

## Next Steps

- [Quick Start Guide](quickstart.md) - Run the API and bot
- [Configuration](../bot/operations/configuration.md) - Detailed environment setup
- [Development Workflow](../contributing/workflow.md) - How to contribute
