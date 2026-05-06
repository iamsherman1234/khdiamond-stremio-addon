#!/bin/bash
source /root/khdiamond/cron_env.sh

USERS_DIR="/root/khdiamond/users"
LOG="/var/log/khdiamond_users.log"

echo "=== User update started: $(date) ===" >> $LOG

for user_dir in $USERS_DIR/*/; do
    token=$(basename $user_dir)
    cookies="$user_dir/cookies.txt"
    catalog="$user_dir/catalog.json"

    if [ ! -f "$cookies" ]; then
        echo "[$token] No cookies — skipping" >> $LOG
        continue
    fi

    echo "[$token] Starting pipeline..." >> $LOG

    export USER_TOKEN=$token
    export USER_DIR=$user_dir
    export COOKIES_PATH=$cookies
    export CATALOG_PATH=$catalog

    python3 /root/khdiamond/user_scrape.py >> $LOG 2>&1
    if [ $? -ne 0 ]; then
        echo "[$token] Scrape failed — skipping" >> $LOG
        continue
    fi

    python3 /root/khdiamond/user_resolve.py >> $LOG 2>&1
    if [ $? -ne 0 ]; then
        echo "[$token] Resolve failed — skipping" >> $LOG
        continue
    fi

    python3 /root/khdiamond/user_sync.py >> $LOG 2>&1
    echo "[$token] Done" >> $LOG
done

echo "=== User update finished: $(date) ===" >> $LOG
