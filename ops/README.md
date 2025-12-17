# Database Backups and Dev Refresh

## Overview

This setup provides two automated database maintenance tasks driven by GitHub Actions and executed on the server:

* **Nightly production backup**
  A scheduled GitHub Actions workflow SSHes into the server and runs a script that uses `pg_dump` inside the production Postgres container. The backup is written to a fixed location on the host and overwrites the previous backup.

* **Weekly dev refresh**
  A scheduled GitHub Actions workflow SSHes into the server and runs a script that:

  1. Creates a fresh production backup.
  2. Drops and recreates the dev database.
  3. Restores the latest production backup into the dev database.

All database credentials are read from the Postgres container environment at runtime. No credentials are stored on the host or in GitHub Actions.

---

## Prepare the directories

Create the host directory that will store the database backup file:

```bash
sudo mkdir -p /var/backups/genji/postgres
```

Configure permissions so the SSH user running the scripts can write backups:

```bash
sudo groupadd -f genji-backup
sudo usermod -aG genji-backup <ssh-user>

sudo chown -R root:genji-backup /var/backups/genji/postgres
sudo chmod 2770 /var/backups/genji/postgres
```

Log out and back in for group membership to take effect.

This directory must be bind-mounted into both the production and dev Postgres containers.

---

## Script location on the server

The repository contains reference scripts under the `ops/` directory alongside this README.

On the server, these scripts must be placed at:

```text
/opt/genji/scripts/backup_prod_db.sh
/opt/genji/scripts/refresh_dev_from_prod.sh
```

The versions in the repository are not executed directly; they are copied to these paths on the server.

---

## Prepare the scripts for execution

After copying the scripts to the server, ensure they are executable and accessible:

```bash
sudo mkdir -p /opt/genji/scripts
sudo chmod 755 /opt/genji /opt/genji/scripts

sudo chmod 755 /opt/genji/scripts/backup_prod_db.sh
sudo chmod 755 /opt/genji/scripts/refresh_dev_from_prod.sh
```

The SSH user must also have permission to run Docker commands.

---

## Required GitHub Secrets

The GitHub Actions workflows require the following secrets to be configured in the repository:

| Secret Name                   | Description                             |
| ----------------------------- | --------------------------------------- |
| `SERVER_HOST_IP`              | Server hostname or IP address           |
| `SERVER_HOST_USER`            | SSH user on the server                  |
| `SERVER_HOST_SSH_PRIVATE_KEY` | Private SSH key used for authentication |
