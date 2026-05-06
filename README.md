# 💎 KhDiamond Stremio Addon

A private, self-hosted Stremio addon that serves Khmer-dubbed movies purchased from [khdiamond.net](https://khdiamond.net) — with multi-user support, redundant streaming, and fully automated catalog updates.

---

## Features

- 🎬 **Personal library** — streams your purchased movies directly from khdiamond CDN
- 👥 **Multi-user** — other users can upload their own cookies and get a personal addon URL
- 🔄 **Auto-sync** — nightly pipeline scrapes purchases, resolves stream IDs, updates catalog
- 🌐 **Redundant streams** — 2 CDNs × 2 MediaFlow proxies × 3 qualities = up to 12 stream options per movie
- ☁️ **Cloudflare Worker** — serves catalog from KV for high availability
- 📺 **4K support** — detects and serves 4K streams where available

---

## Architecture

```
khdiamond.net (purchases)
        ↓
server_scrape.py / user_scrape.py
        ↓
server_resolve.py / user_resolve.py
        ↓
Google Sheet (personal) / local JSON (per-user)
        ↓
sync_catalog.py / user_sync.py
  → scrapes metadata from khdiamond.net
  → fetches IMDB ID + runtime from TMDB
  → writes catalog.json
        ↓
┌─────────────────────────────────────────┐
│  Stremio Addon (2 endpoints)            │
│  1. Cloudflare Worker (primary)         │
│     reads catalog from KV               │
│  2. S10+ Node.js addon (fallback)       │
│     reads catalog.json locally          │
└─────────────────────────────────────────┘
        ↓
Stream matrix per movie:
  {quality} × {CDN} × {MediaFlow}
  1080p | CDN1 | S10
  1080p | CDN1 | Cloud
  1080p | CDN2 | S10
  1080p | CDN2 | Cloud
  720p  | CDN1 | S10
  ...
  (+ 4K variants if available)
        ↓
┌─────────────────────────────────────────┐
│  MediaFlow Proxy (2 instances)          │
│  Primary  → S10+ home server            │
│  Fallback → Render.com free tier        │
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│  CDN                                    │
│  CDN1 → media-1.khdmcloud.online        │
│  CDN2 → khdiamondcdn.asia               │
└─────────────────────────────────────────┘
```

---

## Repository Structure

```
khdiamond-stremio-addon/
├── pipeline/                  # Server-side pipeline scripts
│   ├── server_scrape.py       # Personal: scrape → Google Sheet
│   ├── server_resolve.py      # Personal: resolve IDs → Google Sheet
│   ├── user_scrape.py         # Per-user: scrape → local JSON
│   ├── user_resolve.py        # Per-user: resolve IDs → local JSON
│   ├── user_sync.py           # Per-user: metadata + catalog.json
│   ├── sync_catalog.py        # Personal: metadata + catalog.json
│   ├── drive_manager.py       # Google Sheets/Drive auth
│   └── scripts/
│       └── upload_catalog_to_kv.py  # Push catalog to Cloudflare KV
├── worker/                    # Cloudflare Worker
│   ├── src/
│   │   └── index.js           # Worker entrypoint
│   └── wrangler.toml          # Worker config
├── ui/                        # Multi-user web UI
│   └── web_ui.py              # FastAPI app (port 7003)
├── addon/                     # Personal Stremio addon
│   └── index.js               # Node.js addon server (port 7002)
├── docs/                      # Documentation
│   ├── SETUP.md               # Full setup guide
│   ├── MULTI_USER.md          # Multi-user guide
│   └── ARCHITECTURE.md        # Technical architecture
├── update.sh                  # Manual update script
├── update_all_users.sh        # Nightly cron for all users
└── README.md                  # This file
```

---

## Quick Start

### Prerequisites
- Ubuntu server (tested on Samsung S10+ via DroidSpaces)
- Python 3.12+
- Node.js 18+
- Cloudflare account (free)
- Google Cloud service account (for Sheets API)
- TMDB API token (free)
- MediaFlow proxy instance(s)

### Personal Setup
See [docs/SETUP.md](docs/SETUP.md)

### Multi-User Setup
See [docs/MULTI_USER.md](docs/MULTI_USER.md)

---

## Stremio Install URLs

| Source | URL |
|---|---|
| Cloudflare Worker (primary) | `https://khdiamond.{account}.workers.dev/manifest.json` |
| S10+ direct (fallback) | `https://{your-domain}/khdiamond/manifest.json` |
| Per-user | `https://{your-domain}/khdiamond-ui/u/{token}/manifest.json` |

---

## Cron Schedule

| Time | Script | Purpose |
|---|---|---|
| 12:00 AM | `server_scrape.py` | Scrape personal purchases |
| 12:30 AM | `server_resolve.py` | Resolve personal movie IDs |
| 1:00 AM | `sync_catalog.py` + KV upload | Update personal catalog |
| 2:00 AM | `update_all_users.sh` | Refresh all user catalogs |

---

## Manual Update

```bash
khdupdate           # personal pipeline
```

Or via PicoClaw Telegram bot: `run khdupdate`

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `GDRIVE_SERVICE_ACCOUNT` | Google service account JSON |
| `TMDB_ACCESS_TOKEN` | TMDB API bearer token |
| `MEDIAFLOW_URL` | Primary MediaFlow proxy URL |
| `MEDIAFLOW_URL2` | Fallback MediaFlow proxy URL |
| `MEDIAFLOW_PASSWORD` | MediaFlow API password |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token |
| `CF_ACCOUNT_ID` | Cloudflare account ID |
| `CF_KV_NAMESPACE` | KV namespace ID |
| `COOKIES_PATH` | Path to khdiamond.net cookies.txt |
| `ADDON_URL` | Public URL of the addon |

---

## Tech Stack

| Component | Technology |
|---|---|
| Pipeline | Python 3.12 |
| Personal addon | Node.js + stremio-addon-sdk |
| Multi-user UI | FastAPI + uvicorn |
| Edge catalog | Cloudflare Workers + KV |
| Stream proxy | MediaFlow proxy |
| Metadata | khdiamond.net scraping + TMDB API |
| Auth (Sheets) | Google service account |

---

## License

Private repository — not for public distribution.
