#!/bin/bash
source /root/khdiamond/cron_env.sh
echo "=== Scraping purchases ===" 
python3 /root/khdiamond/server_scrape.py
echo "=== Resolving IDs ==="
python3 /root/khdiamond/server_resolve.py
echo "=== Syncing catalog ==="
python3 /root/khdiamond/sync_catalog.py
echo "=== Uploading to Cloudflare KV ==="
python3 /root/khdiamond/scripts/upload_catalog_to_kv.py
echo "=== Done ==="
