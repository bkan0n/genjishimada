# Backups and Dev Refresh

This section documents the database backup flow and the weekly refresh of the dev database.

## Overview

- **Nightly prod backup** runs on a schedule and creates a fresh database dump.
- **Weekly dev refresh** replaces the dev database with the latest prod backup.
- **Zerobyte (Restic)** uploads the backup file from the host to the Cloudflare R2 bucket.

The backup bucket is `genji-db-backups` (R2), and the host directory is `/var/backups/genji/postgres`.

## Nightly Production Backup

Workflow: `.github/workflows/db-backup-nightly.yml`

- Runs daily at 2:00 AM America/Chicago.
- SSHes to the server and executes `/opt/genji/scripts/backup_prod_db.sh`.

Script: `ops/backup_prod_db.sh`

- Uses `pg_dump -Fc` inside the `genjishimada-db` container.
- Writes to `/var/backups/genji/postgres/genjishimada-prod.dump` on the host.
- Overwrites the previous dump atomically.

## Weekly Dev Refresh

Workflow: `.github/workflows/db-refresh-dev-weekly.yml`

- Runs Sundays at 2:00 AM America/Chicago.
- SSHes to the server and executes `/opt/genji/scripts/refresh_dev_from_prod.sh`.

Script: `ops/refresh_dev_from_prod.sh`

1) Runs the production backup script.
2) Drops and recreates the dev database in `genjishimada-db-dev`.
3) Restores the latest prod dump with `pg_restore --no-owner --no-privileges`.

This keeps dev aligned with prod data while avoiding cross-env ownership issues.

## Zerobyte / Restic Uploads

Zerobyte is used as a GUI wrapper for Restic. It uploads the backup dump stored in
`/var/backups/genji/postgres` to the Cloudflare R2 bucket `genji-db-backups`.

The backup workflow itself only writes the dump to disk; the upload happens via Restic.

## Server Setup Notes

From `ops/README.md`:

- Create `/var/backups/genji/postgres` on the host.
- Add the SSH user to the `genji-backup` group and grant write access.
- Copy scripts from `ops/` to `/opt/genji/scripts/` and mark them executable.

The Postgres containers bind-mount `/var/backups/genji/postgres` so the dump is accessible
on the host for Restic uploads.
