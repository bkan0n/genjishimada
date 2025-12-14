#!/usr/bin/env bash
set -euo pipefail

ADMIN_USER="${RABBITMQ_USER:-admin}"
ADMIN_PASS="${RABBITMQ_PASS:-admin}"
VHOST="${RABBITMQ_VHOST:-/}"

echo "[init] Waiting for RabbitMQ application to be running..."
# wait until the *rabbit* app is fully running, not just the BEAM node
for i in {1..120}; do
  if rabbitmq-diagnostics -q check_running >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [ "$i" -eq 120 ]; then
    echo "[init] Timeout waiting for RabbitMQ to be running"; exit 1
  fi
done

# idempotent user + perms
if rabbitmqctl list_users --quiet | awk '{print $1}' | grep -qx "$ADMIN_USER"; then
  echo "[init] User '$ADMIN_USER' exists; updating password and tags..."
  rabbitmqctl change_password "$ADMIN_USER" "$ADMIN_PASS" || true
  rabbitmqctl set_user_tags "$ADMIN_USER" administrator || true
else
  echo "[init] Creating user '$ADMIN_USER'..."
  rabbitmqctl add_user "$ADMIN_USER" "$ADMIN_PASS"
  rabbitmqctl set_user_tags "$ADMIN_USER" administrator
fi

rabbitmqctl add_vhost "$VHOST" 2>/dev/null || true
rabbitmqctl set_permissions -p "$VHOST" "$ADMIN_USER" ".*" ".*" ".*"

echo "[init] Provisioning complete."
