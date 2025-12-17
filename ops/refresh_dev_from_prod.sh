#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/backup_prod_db.sh"

DEV_CONTAINER="genjishimada-db-dev"
BACKUP_FILE="/var/backups/genji/postgres/genjishimada-prod.dump"

PGUSER="$(docker exec "$DEV_CONTAINER" /bin/sh -lc 'printf "%s" "$POSTGRES_USER"' )"
PGDB="$(docker exec "$DEV_CONTAINER" /bin/sh -lc 'printf "%s" "$POSTGRES_DB"' )"

# Terminate active connections to the dev database
docker exec "$DEV_CONTAINER" /bin/sh -lc \
  "psql -U \"$PGUSER\" -d postgres -v ON_ERROR_STOP=1 -c \
   \"SELECT pg_terminate_backend(pid)
      FROM pg_stat_activity
      WHERE datname = '$PGDB'
        AND pid <> pg_backend_pid();\""

# Drop and recreate the dev database
docker exec "$DEV_CONTAINER" /bin/sh -lc \
  "psql -U \"$PGUSER\" -d postgres -v ON_ERROR_STOP=1 -c \
   \"DROP DATABASE IF EXISTS \\\"$PGDB\\\";\""

docker exec "$DEV_CONTAINER" /bin/sh -lc \
  "psql -U \"$PGUSER\" -d postgres -v ON_ERROR_STOP=1 -c \
   \"CREATE DATABASE \\\"$PGDB\\\" OWNER \\\"$PGUSER\\\";\""

# Restore (ignore ownership/privileges to avoid cross-env issues)
docker exec -i "$DEV_CONTAINER" /bin/sh -lc \
  "pg_restore -U \"$PGUSER\" -d \"$PGDB\" --no-owner --no-privileges --exit-on-error" < "$BACKUP_FILE"
