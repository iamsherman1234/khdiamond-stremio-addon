# Personal Setup Guide

This guide covers setting up the KhDiamond addon for your own personal use on a self-hosted server.

---

## 1. Prerequisites

- Ubuntu 20.04+ server (or Android phone running DroidSpaces/UserLAnd)
- Python 3.12+
- Node.js 18+
- A Cloudflare account (free)
- A Google Cloud project with service account
- A TMDB account (free API token)
- MediaFlow proxy running (self-hosted or cloud)

---

## 2. Clone the Repo

```bash
git clone https://github.com/YOUR_USERNAME/khdiamond-stremio-addon.git /root/khdiamond
cd /root/khdiamond
```

---

## 3. Install Python Dependencies

```bash
pip3 install requests beautifulsoup4 pandas gspread google-auth google-auth-oauthlib \
             google-api-python-client fastapi uvicorn python-multipart --break-system-packages
```

---

## 4. Install Node.js Dependencies

```bash
cd addon
npm install
cd ..
```

---

## 5. Configure Environment

```bash
cp cron_env.sh.example cron_env.sh
nano cron_env.sh
```

Fill in all values:

```bash
export GDRIVE_SERVICE_ACCOUNT='{"type":"service_account",...}'  # paste full JSON
export TMDB_ACCESS_TOKEN="your_tmdb_bearer_token"
export MEDIAFLOW_URL="https://your-domain/mediaflow-py"
export MEDIAFLOW_URL2="https://your-fallback-mediaflow.onrender.com"
export MEDIAFLOW_PASSWORD="your_mediaflow_password"
export CLOUDFLARE_API_TOKEN="your_cloudflare_token"
export ADDON_URL="https://your-domain/khdiamond"
export COOKIES_PATH="/root/khdiamond/cookies.txt"
```

---

## 6. Export Cookies

1. Install [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension
2. Log in to [khdiamond.net](https://khdiamond.net)
3. Export cookies as `cookies.txt` (Netscape format)
4. Copy to server:

```bash
scp -P 2222 cookies.txt root@YOUR_SERVER_IP:/root/khdiamond/cookies.txt
```

---

## 7. Google Sheet Setup

1. Create a Google Sheet
2. Note the Sheet ID from the URL
3. Share the sheet with your service account email (`Editor` access)
4. Update `SPREADSHEET_ID` in `pipeline/server_scrape.py` and `pipeline/server_resolve.py`

---

## 8. Cloudflare Worker Setup

```bash
cd worker
npm install
wrangler login
wrangler kv:namespace create CATALOG
```

Note the KV namespace ID and update `wrangler.toml`.

Add secrets:
```bash
wrangler secret put MEDIAFLOW_URL
wrangler secret put MEDIAFLOW_URL2
wrangler secret put MEDIAFLOW_PASSWORD
```

Deploy:
```bash
wrangler deploy
```

---

## 9. Run First Sync

```bash
source cron_env.sh
python3 pipeline/server_scrape.py
python3 pipeline/server_resolve.py
python3 pipeline/sync_catalog.py
python3 pipeline/scripts/upload_catalog_to_kv.py
```

---

## 10. Start the Addon Server

```bash
# Create systemd service
cp systemd/khdiamond.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable khdiamond
systemctl start khdiamond
```

---

## 11. Configure Nginx

Add to your nginx config:

```nginx
location /khdiamond/ {
    proxy_pass http://127.0.0.1:7002/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
}
```

---

## 12. Set Up Cron

```bash
crontab -e
```

Add:
```
0 0 * * * source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/pipeline/server_scrape.py >> /var/log/khdiamond_scrape.log 2>&1
30 0 * * * source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/pipeline/server_resolve.py >> /var/log/khdiamond_resolve.log 2>&1
0 1 * * * source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/pipeline/sync_catalog.py >> /var/log/khdiamond_sync.log 2>&1 && python3 /root/khdiamond/pipeline/scripts/upload_catalog_to_kv.py >> /var/log/khdiamond_sync.log 2>&1
0 2 * * * /root/khdiamond/update_all_users.sh
```

---

## 13. Install in Stremio

Go to Stremio → Search → Install addon from URL:

```
https://YOUR_DOMAIN/khdiamond/manifest.json
```

Or use the Cloudflare Worker URL:

```
https://khdiamond.YOUR_ACCOUNT.workers.dev/manifest.json
```

---

## Manual Update

Create system command:
```bash
cp update.sh /usr/local/bin/khdupdate
chmod +x /usr/local/bin/khdupdate
```

Run anytime:
```bash
khdupdate
```
