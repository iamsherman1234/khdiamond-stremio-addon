#!/bin/bash
set -uo pipefail

BASE_DIR="/root/khdiamond"
USERS_DIR="$BASE_DIR/users"
LOG="/var/log/khdiamond_users.log"
overall_status=0

source "$BASE_DIR/cron_env.sh"
shopt -s nullglob

echo "=== User update started: $(date) ===" >>"$LOG"

user_dirs=("$USERS_DIR"/*/)

if [ "${#user_dirs[@]}" -eq 0 ]; then
    echo "No user directories found." >>"$LOG"
fi

for user_dir in "${user_dirs[@]}"; do
    token=$(basename "$user_dir")
    cookies="${user_dir}cookies.txt"
    catalog="${user_dir}catalog.json"

    if [ ! -f "$cookies" ]; then
        echo "[$token] No cookies — skipping" >>"$LOG"
        overall_status=1
        continue
    fi

    echo "[$token] Starting pipeline..." >>"$LOG"

    export USER_TOKEN="$token"
    export USER_DIR="$user_dir"
    export COOKIES_PATH="$cookies"
    export CATALOG_PATH="$catalog"

    if ! python3 "$BASE_DIR/user_scrape.py" >>"$LOG" 2>&1; then
        echo "[$token] Scrape failed — keeping existing catalog" >>"$LOG"
        overall_status=1
        continue
    fi

    if ! python3 "$BASE_DIR/user_resolve.py" >>"$LOG" 2>&1; then
        echo "[$token] Resolve failed — keeping existing catalog" >>"$LOG"
        overall_status=1
        continue
    fi

    if ! python3 "$BASE_DIR/user_sync.py" >>"$LOG" 2>&1; then
        echo "[$token] Metadata sync failed — keeping existing catalog" >>"$LOG"
        overall_status=1
        continue
    fi

    echo "[$token] Done" >>"$LOG"
done

echo "=== User update finished: $(date), status=$overall_status ===" >>"$LOG"
exit "$overall_status"
