#!/bin/bash
set -uo pipefail

BASE_DIR="/root/khdiamond"
LOG="/var/log/khdiamond_daily.log"
LOCK="/tmp/khdiamond_daily_update.lock"

exec >>"$LOG" 2>&1
exec 9>"$LOCK"

if ! /usr/bin/flock -n 9; then
  echo "=== UI user update skipped: already running at $(date) ==="
  exit 0
fi

echo
echo "=== UI user update started: $(date) ==="

cd "$BASE_DIR" || exit 1

if "$BASE_DIR/update_all_users.sh"; then
  status=0
else
  status=$?
fi

echo "=== UI user update finished: $(date), status=$status ==="
exit "$status"
