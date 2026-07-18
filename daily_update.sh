#!/bin/bash
set -uo pipefail

BASE_DIR="/root/khdiamond"
LOG="/var/log/khdiamond_daily.log"
LOCK="/tmp/khdiamond_daily_update.lock"

exec >> "$LOG" 2>&1

(
  if ! /usr/bin/flock -n 9; then
    echo "=== KhDiamond daily update skipped: already running at $(date) ==="
    exit 0
  fi

  echo
  echo "=== KhDiamond daily update started: $(date) ==="

  cd "$BASE_DIR" || exit 1

  if [ -x "$BASE_DIR/.venv/bin/python3" ]; then
    export PATH="$BASE_DIR/.venv/bin:$PATH"
  fi

  if [ -f "$BASE_DIR/cron_env.sh" ]; then
    # shellcheck disable=SC1091
    source "$BASE_DIR/cron_env.sh"
  fi

  echo "--- Public catalog metadata refresh ---"
  python3 "$BASE_DIR/scrape_full_catalog.py"
  public_status=$?
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
