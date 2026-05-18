#!/bin/bash
set -u

BASE_DIR="/root/khdiamond"
LOG="/var/log/khdiamond_daily.log"
LOCK="/tmp/khdiamond_daily_update.lock"

exec >> "$LOG" 2>&1

if ! /usr/bin/flock -n "$LOCK" true; then
  echo "=== KhDiamond daily update skipped: already running at $(date) ==="
  exit 0
fi

(
  /usr/bin/flock -n 9 || exit 0

  echo
  echo "=== KhDiamond daily update started: $(date) ==="

  cd "$BASE_DIR" || exit 1

  if [ -f "$BASE_DIR/cron_env.sh" ]; then
    # shellcheck disable=SC1091
    source "$BASE_DIR/cron_env.sh"
  fi

  echo "--- Public catalog scrape/upload ---"
  python3 "$BASE_DIR/scrape_full_catalog.py"
  public_status=$?
  if [ "$public_status" -eq 0 ]; then
    python3 "$BASE_DIR/scripts/upload_full_catalog_to_kv.py"
    public_status=$?
  fi
  echo "--- Public catalog finished with status $public_status ---"

  echo "--- Per-user catalog refresh ---"
  "$BASE_DIR/update_all_users.sh"
  users_status=$?
  echo "--- Per-user refresh finished with status $users_status ---"

  echo "=== KhDiamond daily update finished: $(date) public=$public_status users=$users_status ==="

  if [ "$public_status" -ne 0 ] || [ "$users_status" -ne 0 ]; then
    exit 1
  fi
) 9>"$LOCK"
