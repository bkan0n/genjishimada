#!/usr/bin/env bash
set -euo pipefail

PROD_CONTAINER="genjishimada-db"
BACKUP_DIR="/var/backups/genji/postgres"
BACKUP_FILE="${BACKUP_DIR}/genjishimada-prod.dump"
TMP_FILE="${BACKUP_FILE}.tmp"

mkdir -p "$BACKUP_DIR"

# Read DB name/user from container env (no host-stored creds)
PGUSER="$(docker exec "$PROD_CONTAINER" /bin/sh -lc 'printf "%s" "$POSTGRES_USER"' )"
PGDB="$(docker exec "$PROD_CONTAINER" /bin/sh -lc 'printf "%s" "$POSTGRES_DB"' )"

# Custom format (-Fc) is best for reliable restore via pg_restore
docker exec "$PROD_CONTAINER" /bin/sh -lc \
  "pg_dump -Fc -U \"$PGUSER\" -d \"$PGDB\"" > "$TMP_FILE"

# Atomic replace
mv -f "$TMP_FILE" "$BACKUP_FILE"

# Optional: verify file is non-empty
test -s "$BACKUP_FILE"
