# Multi-User Setup Guide

This guide covers deploying the KhDiamond web UI so other khdiamond.net users can get their own personal Stremio addon.

---

## How It Works

1. User visits `https://your-domain/khdiamond-ui/`
2. User uploads their `cookies.txt` (exported from browser)
3. System assigns a unique token and starts the pipeline in background
4. After ~5 minutes, user gets a personal addon URL
5. User installs the addon URL in Stremio
6. Catalog auto-refreshes nightly

Each user's data is isolated in `/root/khdiamond/users/{token}/`.

---

## User Data Structure

```
/root/khdiamond/users/
└── {token}/
    ├── cookies.txt        # User's khdiamond.net cookies
    ├── meta.json          # Token metadata (created date)
    ├── library_raw.json   # Scraped purchases
    ├── list.json          # Resolved movie IDs
    ├── catalog.json       # Final catalog with metadata
    ├── meta_cache.json    # Metadata cache (speeds up re-sync)
    ├── pipeline.log       # Pipeline execution log
    ├── running.txt        # Exists while pipeline is running
    ├── error.txt          # Exists if pipeline failed
    └── expired.txt        # Exists if cookies expired
```

---

## User Status States

| State | Meaning |
|---|---|
| `pending` | Pipeline is running |
| `ready` | Catalog built, addon works |
| `error` | Pipeline failed |
| `expired` | Cookies expired, needs re-upload |
| `not_found` | Token doesn't exist |

---

## Installation

### 1. Install Dependencies

```bash
pip3 install fastapi uvicorn python-multipart --break-system-packages
```

### 2. Configure Environment

Make sure `khdiamond.env` has all required variables (single-line values, no `export`):

```
GDRIVE_SERVICE_ACCOUNT={"type":"service_account",...}
TMDB_ACCESS_TOKEN=your_token
MEDIAFLOW_URL=https://your-domain/mediaflow-py
MEDIAFLOW_URL2=https://fallback.onrender.com
MEDIAFLOW_PASSWORD=your_password
COOKIES_PATH=/root/khdiamond/cookies.txt
ADDON_URL=https://your-domain
```

### 3. Create Systemd Service

```bash
cat > /etc/systemd/system/khdiamond-ui.service << 'EOF'
[Unit]
Description=KhDiamond Multi-User Addon UI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/khdiamond
EnvironmentFile=/root/khdiamond/khdiamond.env
ExecStart=/usr/bin/python3 /root/khdiamond/ui/web_ui.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable khdiamond-ui
systemctl start khdiamond-ui
```

### 4. Configure Nginx

Add to your nginx config:

```nginx
location /khdiamond-ui/ {
    proxy_pass http://127.0.0.1:7003/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
}
```

Reload nginx:
```bash
nginx -t && systemctl reload nginx
```

### 5. Add Nightly Cron for All Users

```bash
crontab -e
```

Add:
```
0 2 * * * /root/khdiamond/update_all_users.sh
```

---

## User Guide (Share with Users)

### Getting Your Addon

1. Go to `https://your-domain/khdiamond-ui/`
2. Export your cookies from khdiamond.net using the [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension
3. Upload the `cookies.txt` file
4. Wait 3–5 minutes for your catalog to build
5. Copy your addon URL and install it in Stremio

### Refreshing Your Catalog

If you bought new movies or your cookies expired:
1. Go to your status page: `https://your-domain/khdiamond-ui/status/{token}`
2. Click **Re-upload Cookies**
3. Upload fresh cookies
4. Wait for rebuild

### Bookmark Your Status Page

Save your status page URL — it's the only way to manage your addon. The token never expires unless you delete it.

---

## Admin Commands

```bash
# Check all users
ls /root/khdiamond/users/

# Check a specific user's log
tail -f /root/khdiamond/users/{token}/pipeline.log

# Manually re-run pipeline for a user
source /root/khdiamond/cron_env.sh
USER_TOKEN={token} \
USER_DIR=/root/khdiamond/users/{token} \
COOKIES_PATH=/root/khdiamond/users/{token}/cookies.txt \
CATALOG_PATH=/root/khdiamond/users/{token}/catalog.json \
python3 /root/khdiamond/pipeline/user_scrape.py

# Check service status
systemctl status khdiamond-ui

# View service logs
journalctl -u khdiamond-ui -n 50
```

---

## Limitations

- **~30 users max** on free-tier hardware
- **Cookies expire** periodically — users must re-upload
- **Pipeline takes ~5 minutes** per user
- **Render.com cold start** — fallback MediaFlow takes ~30s after 15min idle
- **Shared MediaFlow** — all users share the same proxy instances
