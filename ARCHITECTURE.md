# Technical Architecture

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA PIPELINE                           │
│                                                                 │
│  khdiamond.net                                                  │
│       ↓ (cookies auth)                                          │
│  Scraper → library_raw (Sheet / local JSON)                     │
│       ↓                                                         │
│  Resolver → list (Sheet / local JSON)                           │
│       ↓ (khdiamond.net + TMDB API)                              │
│  Sync → catalog.json                                            │
│       ↓                                                         │
│  KV Uploader → Cloudflare KV                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        ADDON LAYER                              │
│                                                                 │
│  Cloudflare Worker (primary)     Node.js Addon (fallback)       │
│  reads from KV                   reads catalog.json             │
│  always online                   depends on S10+ uptime         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       STREAM MATRIX                             │
│                                                                 │
│  Per movie: quality × CDN × MediaFlow                           │
│                                                                 │
│  4K    | CDN1 | S10    ←── if movie_id_4k exists               │
│  4K    | CDN1 | Cloud                                           │
│  4K    | CDN2 | S10                                             │
│  4K    | CDN2 | Cloud                                           │
│  1080p | CDN1 | S10                                             │
│  1080p | CDN1 | Cloud                                           │
│  1080p | CDN2 | S10                                             │
│  1080p | CDN2 | Cloud                                           │
│  720p  | CDN1 | S10                                             │
│  720p  | CDN1 | Cloud                                           │
│  720p  | CDN2 | S10                                             │
│  720p  | CDN2 | Cloud                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      MEDIAFLOW PROXY                            │
│                                                                 │
│  S10 (primary)  → sudolocal.qzz.io/mediaflow-py                │
│  Cloud (fallback) → mediaflow-proxy.onrender.com               │
│                                                                 │
│  Proxies HLS streams, handles CORS, adds auth headers          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                           CDN                                   │
│                                                                 │
│  CDN1 → media-1.khdmcloud.online/hls/{id}/{quality}.m3u8       │
│  CDN2 → khdiamondcdn.asia/hls/{id}/{quality}.m3u8              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Personal vs Per-User Pipeline

| Step | Personal | Per-User |
|---|---|---|
| Scrape | `server_scrape.py` → Google Sheet | `user_scrape.py` → `library_raw.json` |
| Resolve | `server_resolve.py` → Google Sheet | `user_resolve.py` → `list.json` |
| Sync | `sync_catalog.py` → `catalog.json` | `user_sync.py` → `catalog.json` |
| KV Upload | `upload_catalog_to_kv.py` | Not needed (S10+ serves directly) |
| Trigger | `khdupdate` / cron | web upload / cron |

---

## Catalog Entry Schema

```json
{
  "khd_id": "khd_355eeU5IE96e36A",
  "movie_id": "355eeU5IE96e36A",
  "movie_id_4k": "",
  "slug": "a-brother-and-7-siblings",
  "type": "movie",
  "title_khmer": "ទឹកភ្នែកក្មេងកំព្រា – A Brother and 7 Siblings",
  "title_english": "A Brother and 7 Siblings",
  "year": "2024",
  "poster": "https://khdiamond.net/wp-content/uploads/...",
  "backdrop": "https://image.tmdb.org/t/p/w1280/...",
  "genres": ["Drama", "Family", "និយាយខ្មែរ"],
  "overview": "Description text...",
  "imdb_id": "tt32881480",
  "tmdb_id": "12345",
  "imdb_rating": "8.5",
  "runtime": "120 min"
}
```

---

## Stream URL Construction

```
MediaFlow base URL
  + /proxy/hls/manifest.m3u8
  + ?api_password={password}
  + &d={CDN URL encoded}

CDN URL pattern:
  https://{cdn_host}/hls/{movie_id}/{quality}.m3u8
```

---

## Multi-User Web UI

```
FastAPI app (port 7003)

Routes:
  GET  /                          Upload page
  POST /khdiamond-ui/upload       Receive cookies → generate token → run pipeline
  GET  /khdiamond-ui/status/{t}   Show status (pending/ready/error/expired)
  GET  /khdiamond-ui/refresh/{t}  Re-upload page
  POST /khdiamond-ui/refresh/{t}  Receive new cookies → re-run pipeline

  GET  /u/{token}/manifest.json   Per-user Stremio manifest
  GET  /u/{token}/catalog/...     Per-user catalog
  GET  /u/{token}/meta/...        Per-user metadata
  GET  /u/{token}/stream/...      Per-user streams
```

---

## Cloudflare Worker

```javascript
// Reads catalog from KV
const raw = await env.CATALOG.get("catalog.json")
const catalog = JSON.parse(raw)

// Builds stream URLs
const streams = qualities × CDNs × MediaFlowServers
```

KV is updated nightly by `upload_catalog_to_kv.py` after `sync_catalog.py` runs.

---

## Authentication Flow

```
khdiamond.net session cookies (Netscape format)
  → loaded by MozillaCookieJar
  → attached to requests.Session
  → used for:
    - GET /my-account/ (scrape purchases)
    - GET /movies/{slug}/ (check 4K availability)
    - GET /episodes/{slug}/ (get episode post IDs)
    - POST /wp-admin/admin-ajax.php (resolve stream IDs)
```

---

## Failure Modes & Mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| S10+ down | Streams fail if S10 MediaFlow down | Cloud MediaFlow fallback |
| Cookies expired | Nightly sync fails | `expired.txt` marker + UI warning |
| Google Sheet quota | Personal sync fails | Retry next night |
| Cloudflare KV stale | Worker serves old catalog | `khdupdate` re-uploads |
| Render cold start | 30s delay on first stream | Acceptable for fallback use |
| CDN1 down | CDN1 streams fail | CDN2 fallback in stream list |
