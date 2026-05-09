# 💎 KhDiamond Stremio Addon

A self-hosted, fully automated Stremio addon ecosystem for Khmer-dubbed movies from [khdiamond.net](https://khdiamond.net). Supports personal use, multi-user deployment, and a public catalog for browsing all available titles.

---

## 📺 What It Does

| Addon | URL | Purpose |
|---|---|---|
| Personal Streaming | `https://your-domain/khdiamond/manifest.json` | Stream your purchased movies |
| Cloudflare Worker | `https://khdiamond.{account}.workers.dev/manifest.json` | Backup/primary streaming endpoint |
| Multi-User | `https://your-domain/khdiamond-ui/u/{token}/manifest.json` | Per-user personal addon |
| Catalog | `https://khdiamond-catalog.{account}.workers.dev/manifest.json` | Browse all 400+ KhDiamond titles |

---

## 🏗️ Architecture

```
khdiamond.net purchases
        ↓
Pipeline (scrape → resolve → sync)
        ↓
Google Sheet (personal) / local JSON (per-user)
        ↓
catalog.json → Cloudflare KV
        ↓
┌─────────────────────────────────────┐
│  3 Streaming Addon Endpoints        │
│  • S10+ Node.js (port 7002)         │
│  • Cloudflare Worker                │
│  • Per-user FastAPI (port 7003)     │
└─────────────────────────────────────┘
        ↓
Stream Matrix per movie:
  4K/1080p/720p × CDN1/CDN2 × S10/Cloud
  = up to 12 stream options
        ↓
MediaFlow Proxy (S10+ primary, Render fallback)
        ↓
CDN (media-1.khdmcloud.online / khdiamondcdn.asia)
```

---

## 📁 Repository Structure

```
khdiamond-stremio-addon/
├── index.js                        # Personal S10+ Stremio addon (port 7002)
├── web_ui.py                       # Multi-user FastAPI web UI (port 7003)
├── server_scrape.py                # Personal: scrape → Google Sheet
├── server_resolve.py               # Personal: resolve IDs → Google Sheet
├── sync_catalog.py                 # Personal: metadata → catalog.json
├── user_scrape.py                  # Per-user: scrape → local JSON
├── user_resolve.py                 # Per-user: resolve IDs → local JSON
├── user_sync.py                    # Per-user: metadata → catalog.json
├── scrape_full_catalog.py          # Scrape all public khdiamond titles
├── drive_manager.py                # Google Sheets/Drive auth
├── update.sh                       # Manual update script (personal)
├── update_all_users.sh             # Nightly cron for all users
├── scripts/
│   ├── upload_catalog_to_kv.py     # Push personal catalog to KV
│   └── upload_full_catalog_to_kv.py # Push full catalog to KV
├── docs/
│   ├── SETUP.md                    # Personal setup guide
│   ├── MULTI_USER.md               # Multi-user deployment guide
│   └── ARCHITECTURE.md             # Technical deep dive
├── cron_env.sh.example             # Environment variables template
└── .gitignore
```

---

## ⚡ Quick Start

### Prerequisites

- Ubuntu server (tested on Samsung S10+ via DroidSpaces)
- Python 3.12+
- Node.js 18+
- Cloudflare account (free)
- Google Cloud service account with Sheets API enabled
- TMDB API token (free at [themoviedb.org](https://themoviedb.org))
- MediaFlow proxy instance(s)
- khdiamond.net account with purchased movies

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/khdiamond-stremio-addon.git /root/khdiamond
cd /root/khdiamond

# Python dependencies
pip3 install requests beautifulsoup4 pandas gspread google-auth \
             google-auth-oauthlib google-api-python-client \
             fastapi uvicorn python-multipart --break-system-packages

# Node.js dependencies
npm install
```

### 2. Configure Environment

```bash
cp cron_env.sh.example cron_env.sh
nano cron_env.sh
```

Fill in all values:

```bash
export GDRIVE_SERVICE_ACCOUNT='{"type":"service_account",...}'  # paste full JSON on one line
export TMDB_ACCESS_TOKEN="your_tmdb_bearer_token"
export MEDIAFLOW_URL="https://your-domain/mediaflow-py"
export MEDIAFLOW_URL2="https://your-fallback.onrender.com"
export MEDIAFLOW_PASSWORD="your_password"
export CLOUDFLARE_API_TOKEN="your_cf_token"
export CF_ACCOUNT_ID="your_cf_account_id"
export ADDON_URL="https://your-domain/khdiamond"
export COOKIES_PATH="/root/khdiamond/cookies.txt"
```

Also create `khdiamond.env` (same content, no `export` prefix) for systemd:

```bash
grep "^export" cron_env.sh | sed 's/^export //' > khdiamond.env
# Then manually fix GDRIVE_SERVICE_ACCOUNT to be on a single line
```

### 3. Export Cookies from Browser

1. Install [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension
2. Log into [khdiamond.net](https://khdiamond.net)
3. Click the extension → export `cookies.txt` (Netscape format)
4. Upload to server:

```bash
scp -P YOUR_PORT cookies.txt root@YOUR_SERVER:/root/khdiamond/cookies.txt
```

### 4. Set Up Cloudflare Worker

```bash
cd /root/khdiamond-worker  # separate repo: khdiamond-stremio-worker
npm install
wrangler login
wrangler kv namespace create CATALOG
# Note the namespace ID, update wrangler.toml
wrangler secret put MEDIAFLOW_URL
wrangler secret put MEDIAFLOW_URL2
wrangler secret put MEDIAFLOW_PASSWORD
wrangler deploy
```

### 5. Run First Sync

```bash
source cron_env.sh
python3 server_scrape.py
python3 server_resolve.py
python3 sync_catalog.py

# Upload to Cloudflare KV
CF_ACCOUNT_ID="your_id" python3 scripts/upload_catalog_to_kv.py
```

### 6. Start Addon Servers

**Personal streaming addon (pm2):**
```bash
pm2 start index.js --name khdiamond --cwd /root/khdiamond
pm2 save
```

**Multi-user web UI (systemd):**
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
ExecStart=/usr/bin/python3 /root/khdiamond/web_ui.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable khdiamond-ui
systemctl start khdiamond-ui
```

### 7. Configure Nginx

```nginx
location /khdiamond/ {
    proxy_pass http://127.0.0.1:7002/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
}

location /khdiamond-ui/ {
    proxy_pass http://127.0.0.1:7003/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
}
```

```bash
nginx -t && systemctl reload nginx
```

### 8. Create Manual Update Command

```bash
cat > /usr/local/bin/khdupdate << 'EOF'
#!/bin/bash
nohup /root/khdiamond/update.sh >> /var/log/khdiamond_update.log 2>&1 &
echo "✓ KhDiamond update started in background (PID $!)"
echo "  Monitor: tail -f /var/log/khdiamond_update.log"
EOF
chmod +x /usr/local/bin/khdupdate
```

### 9. Set Up Cron

```bash
crontab -e
```

```
0 0 * * *  source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/server_scrape.py >> /var/log/khdiamond_scrape.log 2>&1
30 0 * * * source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/server_resolve.py >> /var/log/khdiamond_resolve.log 2>&1
0 1 * * *  source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/sync_catalog.py >> /var/log/khdiamond_sync.log 2>&1 && python3 /root/khdiamond/scripts/upload_catalog_to_kv.py >> /var/log/khdiamond_sync.log 2>&1
0 2 * * *  /root/khdiamond/update_all_users.sh
0 3 * * 0  source /root/khdiamond/cron_env.sh && python3 /root/khdiamond/scrape_full_catalog.py >> /var/log/khdiamond_fullcat.log 2>&1 && python3 /root/khdiamond/scripts/upload_full_catalog_to_kv.py >> /var/log/khdiamond_fullcat.log 2>&1
```

### 10. Install in Stremio

Install both addons for the best experience:

**Streaming addon** (your purchased movies):
```
https://khdiamond.YOUR_ACCOUNT.workers.dev/manifest.json
```

**Catalog addon** (browse all 400+ KhDiamond titles):
```
https://khdiamond-catalog.YOUR_ACCOUNT.workers.dev/manifest.json
```

> When both are installed, clicking any movie from the catalog will automatically show your KhDiamond streams if you own it.

---

## 👥 Multi-User Setup

Users can get their own personal addon by:

1. Visiting `https://your-domain/khdiamond-ui/`
2. Uploading their `cookies.txt` from khdiamond.net
3. Waiting ~5 minutes for the catalog to build
4. Installing the generated addon URL in Stremio

Each user gets a unique token and isolated catalog. Nightly cron refreshes all users automatically.

**Admin commands:**
```bash
# Check all users
ls /root/khdiamond/users/

# View a user's pipeline log
tail -f /root/khdiamond/users/{token}/pipeline.log

# Manually re-run for a user
source /root/khdiamond/cron_env.sh
USER_TOKEN={token} \
USER_DIR=/root/khdiamond/users/{token} \
COOKIES_PATH=/root/khdiamond/users/{token}/cookies.txt \
CATALOG_PATH=/root/khdiamond/users/{token}/catalog.json \
python3 /root/khdiamond/user_scrape.py
```

---

## 🔄 Stream Matrix

Each movie provides up to 12 stream options:

```
Quality  │ CDN  │ Proxy  
─────────┼──────┼────────
4K       │ CDN1 │ S10    
4K       │ CDN1 │ Cloud  
4K       │ CDN2 │ S10    
4K       │ CDN2 │ Cloud  
1080p    │ CDN1 │ S10    
1080p    │ CDN1 │ Cloud  
1080p    │ CDN2 │ S10    
1080p    │ CDN2 │ Cloud  
720p     │ CDN1 │ S10    
720p     │ CDN1 │ Cloud  
720p     │ CDN2 │ S10    
720p     │ CDN2 │ Cloud  
```

4K streams only appear when available on khdiamond.net.

---

## 🗄️ Cron Schedule

| Time | Script | Purpose |
|---|---|---|
| 12:00 AM daily | `server_scrape.py` | Scrape personal purchases |
| 12:30 AM daily | `server_resolve.py` | Resolve movie IDs |
| 1:00 AM daily | `sync_catalog.py` + KV upload | Update personal catalog |
| 2:00 AM daily | `update_all_users.sh` | Refresh all user catalogs |
| 3:00 AM Sunday | `scrape_full_catalog.py` + KV upload | Update public catalog addon |

---

## 🛠️ Manual Commands

```bash
# Update personal catalog (runs in background)
khdupdate

# Monitor update progress
tail -f /var/log/khdiamond_update.log

# Check service status
pm2 status
systemctl status khdiamond-ui

# View logs
pm2 logs khdiamond --lines 50
journalctl -u khdiamond-ui -n 50
```

---

## 🔧 Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `GDRIVE_SERVICE_ACCOUNT` | Google service account JSON (single line) | Personal pipeline |
| `TMDB_ACCESS_TOKEN` | TMDB API bearer token | Metadata sync |
| `MEDIAFLOW_URL` | Primary MediaFlow proxy URL | Streaming |
| `MEDIAFLOW_URL2` | Fallback MediaFlow proxy URL | Streaming fallback |
| `MEDIAFLOW_PASSWORD` | MediaFlow API password | Streaming |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token | KV upload |
| `CF_ACCOUNT_ID` | Cloudflare account ID | KV upload |
| `ADDON_URL` | Public URL of the S10+ addon | Addon manifest |
| `COOKIES_PATH` | Path to khdiamond.net cookies.txt | Scraper |

---

## 🚨 Troubleshooting

### Cookies expired
```bash
# Export fresh cookies, then:
scp -P PORT cookies.txt root@SERVER:/root/khdiamond/cookies.txt
khdupdate
```

### Streams not showing in Stremio
```bash
# Test stream endpoint directly
curl "https://khdiamond.YOUR_ACCOUNT.workers.dev/stream/movie/tt0478970.json"
# Should return 12 streams for Ant-Man (tt0478970)
```

### Catalog not updating
```bash
source /root/khdiamond/cron_env.sh
python3 /root/khdiamond/sync_catalog.py
python3 /root/khdiamond/scripts/upload_catalog_to_kv.py
```

### Multi-user pipeline failed
```bash
# Check error
cat /root/khdiamond/users/{token}/error.txt
cat /root/khdiamond/users/{token}/pipeline.log
```

### KV upload out of memory (S10+)
```bash
# Use curl instead of wrangler
source /root/khdiamond/cron_env.sh
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/storage/kv/namespaces/YOUR_NAMESPACE_ID/values/catalog.json" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary @/root/khdiamond/catalog.json
```

---

## 🔐 Security Notes

- Never commit `cron_env.sh`, `khdiamond.env`, `cookies.txt`, or `service_account.json`
- The `.gitignore` excludes all sensitive files automatically
- MediaFlow password protects streams from unauthorized access
- Per-user tokens are 8-character UUIDs
- All Stremio addon endpoints must be public (Stremio requirement)

---

## 📝 License

Private repository — not for public distribution.
