#!/usr/bin/env bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
VPS_SSH_HOST="genji-vps"  # SSH config entry name
LOCAL_CONTAINER="genjishimada-db-local"
LOCAL_DB="genjishimada"
LOCAL_USER="genji"

# Display usage
usage() {
    echo "Usage: $0 [dev|prod]"
    echo ""
    echo "Import database backup from VPS environment to local development database."
    echo ""
    echo "Arguments:"
    echo "  dev   - Import from development environment"
    echo "  prod  - Import from production environment"
    echo ""
    echo "Examples:"
    echo "  $0 dev   # Import dev database"
    echo "  $0 prod  # Import production database"
    exit 1
}

# Check arguments
if [ $# -ne 1 ]; then
    usage
fi

ENVIRONMENT=$1

# Validate environment argument
if [ "$ENVIRONMENT" != "dev" ] && [ "$ENVIRONMENT" != "prod" ]; then
    echo -e "${RED}Error: Invalid environment. Must be 'dev' or 'prod'${NC}"
    usage
fi

# Set container and database names based on environment
if [ "$ENVIRONMENT" = "prod" ]; then
    REMOTE_CONTAINER="genjishimada-db"
    REMOTE_DB="genjishimada"
    REMOTE_USER="genjishimada"
else
    REMOTE_CONTAINER="genjishimada-db-dev"
    REMOTE_DB="genjishimada"
    REMOTE_USER="genjishimada"
fi

echo -e "${YELLOW}=== Database Import from VPS ${ENVIRONMENT} ===${NC}"
echo ""

# Check if local PostgreSQL container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${LOCAL_CONTAINER}$"; then
    echo -e "${RED}Error: Local PostgreSQL container '${LOCAL_CONTAINER}' is not running${NC}"
    echo "Start it with: docker compose -f docker-compose.local.yml up -d postgres-local"
    exit 1
fi

# Check SSH connectivity
echo -e "${GREEN}[1/4]${NC} Checking SSH connectivity to ${VPS_SSH_HOST}..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${VPS_SSH_HOST}" exit 2>/dev/null; then
    echo -e "${RED}Error: Cannot connect to ${VPS_SSH_HOST}${NC}"
    echo "Ensure your SSH config is set up and you have access to the VPS"
    exit 1
fi
echo -e "${GREEN}✓${NC} SSH connection successful"
echo ""

# Confirm import action
echo -e "${YELLOW}WARNING:${NC} This will:"
echo "  1. Drop the local '${LOCAL_DB}' database"
echo "  2. Recreate it from ${ENVIRONMENT} environment"
echo "  3. All local data will be lost"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Import cancelled"
    exit 0
fi
echo ""

# Drop existing local database
echo -e "${GREEN}[2/4]${NC} Dropping local database..."
docker exec -i "${LOCAL_CONTAINER}" psql -U "${LOCAL_USER}" -c "DROP DATABASE IF EXISTS ${LOCAL_DB};" postgres
echo -e "${GREEN}✓${NC} Database dropped"
echo ""

# Create fresh local database
echo -e "${GREEN}[3/4]${NC} Creating fresh local database..."
docker exec -i "${LOCAL_CONTAINER}" psql -U "${LOCAL_USER}" -c "CREATE DATABASE ${LOCAL_DB};" postgres
echo -e "${GREEN}✓${NC} Database created"
echo ""

# Dump from VPS and import to local
echo -e "${GREEN}[4/4]${NC} Importing database from ${ENVIRONMENT}..."
echo "This may take a few minutes depending on database size..."
ssh "${VPS_SSH_HOST}" "docker exec ${REMOTE_CONTAINER} pg_dump -U ${REMOTE_USER} -d ${REMOTE_DB} --no-owner --no-acl" | \
    docker exec -i "${LOCAL_CONTAINER}" psql -U "${LOCAL_USER}" -d "${LOCAL_DB}" > /dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Import completed successfully!"
    echo ""
    echo -e "${GREEN}Database imported from ${ENVIRONMENT} environment${NC}"
    echo "You can now run your API/bot locally with this data"
else
    echo -e "${RED}Error: Import failed${NC}"
    exit 1
fi
