#!/usr/bin/env bash
#
# seed-tournament-local.sh
#
# Bootstraps tournament categories for LOCAL testing. After migrations the
# `tournaments.categories` table is empty and a freshly-rolled cycle is born
# `pending` -- the pg_cron scheduler only ever *promotes* a pending cycle when an
# existing active cycle becomes due, so the very first cycle never activates on
# its own. This script closes that gap:
#
#   1. Create two categories (idempotent) with XP config:
#        - "Easy / Medium"      difficulties: Easy, Medium
#        - "Hard / Very Hard"   difficulties: Hard, Very Hard
#   2. Roll a map for each (creates a `pending` cycle) via the API.
#   3. Flip that first cycle to `active` (status + started_at) via SQL so you can
#      immediately POST a normal completion (POST /api/v3/completions/) on the
#      cycle's map -- the API auto-detects the active cycle and records the
#      tournament row through the verified pipeline (no bypass submit endpoint).
#
# Re-running is safe: existing categories are reused and a category that already
# has an active cycle is left untouched.
#
# Requirements: bash, curl, jq, and the local Docker Postgres container running.
# The API must be running (just run-api) and reachable at $API_BASE.
#
# Usage:
#   ./scripts/seed-tournament-local.sh
#
# Optional env overrides:
#   API_BASE                     (default http://localhost:8000)
#   API_KEY                      (auto-loaded from .env.local if unset)
#   EASY_MED_CHAMPION_ROLE_ID    Discord role id for the Easy/Medium champion
#   HARD_VH_CHAMPION_ROLE_ID     Discord role id for the Hard/Very Hard champion
#   DB_CONTAINER                 (default genjishimada-db-local)
#   DB_USER / DB_NAME            (default genji / genjishimada)

set -euo pipefail

# --- Resolve repo root so the script works from anywhere -------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Config ----------------------------------------------------------------
API_BASE="${API_BASE:-http://localhost:8000}"
DB_CONTAINER="${DB_CONTAINER:-genjishimada-db-local}"
DB_USER="${DB_USER:-genji}"
DB_NAME="${DB_NAME:-genjishimada}"

# Load API_KEY from .env.local if not already exported.
if [[ -z "${API_KEY:-}" && -f "$REPO_ROOT/.env.local" ]]; then
  API_KEY="$(grep -E '^API_KEY=' "$REPO_ROOT/.env.local" | head -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi
API_KEY="${API_KEY:-}"

# --- Preflight -------------------------------------------------------------
command -v jq   >/dev/null || { echo "[x] jq is required (brew install jq)"; exit 1; }
command -v curl >/dev/null || { echo "[x] curl is required"; exit 1; }

if [[ -z "$API_KEY" ]]; then
  echo "[x] API_KEY not set and not found in .env.local. Export API_KEY=... and retry."
  exit 1
fi

if ! curl -fsS -o /dev/null "$API_BASE/healthcheck" 2>/dev/null; then
  echo "[x] API not reachable at $API_BASE -- start it with: just run-api"
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$DB_CONTAINER"; then
  echo "[x] Postgres container '$DB_CONTAINER' not running."
  echo "    Start infra with: docker compose -f docker-compose.local.yml up -d"
  exit 1
fi

# --- Helpers ---------------------------------------------------------------
psql_q() {
  # Single scalar result, no headers/alignment.
  docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1"
}

api() {
  # api METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "$API_BASE$path" \
      -H "X-API-KEY: $API_KEY" -H "Content-Type: application/json" -d "$body"
  else
    curl -sS -X "$method" "$API_BASE$path" -H "X-API-KEY: $API_KEY"
  fi
}

# create_or_get_category NAME DIFFICULTIES_JSON PARTICIPATION PLACEMENT_JSON STREAK_JSON CHAMPION
# Echoes the category id on stdout.
create_or_get_category() {
  local name="$1" diffs="$2" participation="$3" placement="$4" streak="$5" champion="${6:-}"
  local champion_field="null"
  [[ -n "$champion" ]] && champion_field="$champion"

  local payload
  payload=$(cat <<JSON
{
  "name": "$name",
  "difficulties": $diffs,
  "cycle_frequency": "weekly",
  "participation_xp": $participation,
  "placement_xp": $placement,
  "streak_xp": $streak,
  "champion_role_id": $champion_field
}
JSON
)

  local resp id
  resp="$(api POST /api/v3/tournaments/categories "$payload")"
  id="$(echo "$resp" | jq -r 'try .id // empty')"

  if [[ -n "$id" ]]; then
    echo "    [+] created category '$name' (id=$id)" >&2
  else
    # Likely already exists (unique name) -- look it up.
    id="$(api GET /api/v3/tournaments/categories \
          | jq -r --arg n "$name" '.[] | select(.name==$n) | .id' | head -1)"
    if [[ -n "$id" ]]; then
      echo "    [=] category '$name' already exists (id=$id)" >&2
    else
      echo "[x] Failed to create or find category '$name'. API said:" >&2
      echo "$resp" | jq . >&2 || echo "$resp" >&2
      exit 1
    fi
  fi
  echo "$id"
}

# ensure_active_cycle CATEGORY_ID
ensure_active_cycle() {
  local cid="$1"

  local active_count
  active_count="$(psql_q "SELECT count(*) FROM tournaments.cycles WHERE category_id=$cid AND status='active';")"
  if [[ "$active_count" -gt 0 ]]; then
    echo "    [=] category $cid already has an active cycle -- leaving as-is" >&2
    return 0
  fi

  # Reuse an existing pending cycle if one is sitting there; otherwise roll one.
  local pending_id
  pending_id="$(psql_q "SELECT id FROM tournaments.cycles WHERE category_id=$cid AND status='pending' ORDER BY created_at ASC LIMIT 1;")"

  if [[ -z "$pending_id" ]]; then
    local resp
    resp="$(api POST "/api/v3/tournaments/categories/$cid/select-map")"
    pending_id="$(echo "$resp" | jq -r 'try .id // empty')"
    if [[ -z "$pending_id" ]]; then
      echo "[x] select-map failed for category $cid -- likely no eligible official maps for its difficulties." >&2
      echo "    API said:" >&2
      echo "$resp" | jq . >&2 || echo "$resp" >&2
      echo "    Check: SELECT regexp_replace(difficulty,'\\s*[-+]\\s*\$','') d, count(*)" >&2
      echo "           FROM core.maps WHERE official AND NOT archived AND code IS NOT NULL GROUP BY 1;" >&2
      return 1
    fi
    local code name
    code="$(echo "$resp" | jq -r '.map_code')"
    name="$(echo "$resp" | jq -r '.map_name')"
    echo "    [+] rolled map $code ($name) -> pending cycle $pending_id" >&2
  else
    echo "    [=] reusing existing pending cycle $pending_id" >&2
  fi

  # Activate it -- the scheduler can't bootstrap the first cycle.
  psql_q "UPDATE tournaments.cycles SET status='active', started_at=now() WHERE id=$pending_id;" >/dev/null
  echo "    [✓] activated cycle $pending_id for category $cid" >&2
  echo "$pending_id"
}

# --- XP configuration ------------------------------------------------------
# Tweak these to taste. place = leaderboard position; threshold = consecutive cycles.
EASY_MED_PARTICIPATION=25
EASY_MED_PLACEMENT='[{"place":1,"xp":500},{"place":2,"xp":300},{"place":3,"xp":150}]'
EASY_MED_STREAK='[{"threshold":3,"xp":100},{"threshold":5,"xp":250}]'

HARD_VH_PARTICIPATION=50
HARD_VH_PLACEMENT='[{"place":1,"xp":1000},{"place":2,"xp":600},{"place":3,"xp":300}]'
HARD_VH_STREAK='[{"threshold":3,"xp":200},{"threshold":5,"xp":500}]'

# --- Run -------------------------------------------------------------------
echo "==> Seeding tournament categories against $API_BASE"

echo "--> Easy / Medium"
EM_ID="$(create_or_get_category \
  "Easy / Medium" '["Easy","Medium"]' \
  "$EASY_MED_PARTICIPATION" "$EASY_MED_PLACEMENT" "$EASY_MED_STREAK" \
  "${EASY_MED_CHAMPION_ROLE_ID:-}")"
EM_CYCLE="$(ensure_active_cycle "$EM_ID" || true)"

echo "--> Hard / Very Hard"
HV_ID="$(create_or_get_category \
  "Hard / Very Hard" '["Hard","Very Hard"]' \
  "$HARD_VH_PARTICIPATION" "$HARD_VH_PLACEMENT" "$HARD_VH_STREAK" \
  "${HARD_VH_CHAMPION_ROLE_ID:-}")"
HV_CYCLE="$(ensure_active_cycle "$HV_ID" || true)"

echo
echo "==> Done."
echo "    Easy / Medium     category id=$EM_ID   active cycle=${EM_CYCLE:-<none>}"
echo "    Hard / Very Hard  category id=$HV_ID   active cycle=${HV_CYCLE:-<none>}"
echo
# The map code for the Easy/Medium active cycle -- a normal completion POST on
# this map is auto-detected as a tournament submission by the verified pipeline.
EM_MAP_CODE=""
if [[ -n "${EM_CYCLE:-}" ]]; then
  EM_MAP_CODE="$(psql_q "SELECT m.code FROM tournaments.cycles c JOIN core.maps m ON m.id = c.map_id WHERE c.id=${EM_CYCLE} LIMIT 1;" || true)"
fi
echo "    Submit a tournament time via a NORMAL completion on the cycle's map"
echo "    (the API auto-detects the active cycle -- there is no submit endpoint):"
echo "      curl -sX POST $API_BASE/api/v3/completions/ \\"
echo "        -H \"X-API-KEY: \$API_KEY\" -H 'Content-Type: application/json' \\"
echo "        -d '{\"code\":\"${EM_MAP_CODE:-<map_code>}\",\"user_id\":123,\"time\":45.5,\"screenshot\":\"https://x/y.png\",\"video\":null}' | jq"
echo
echo "    Fast-forward finalization (instead of waiting a week):"
echo "      docker exec -it $DB_CONTAINER psql -U $DB_USER -d $DB_NAME -c \\"
echo "        \"UPDATE tournaments.cycles SET started_at = now() - interval '8 days' WHERE id=${EM_CYCLE:-<id>}; SELECT tournaments.process_cycle_transitions();\""
