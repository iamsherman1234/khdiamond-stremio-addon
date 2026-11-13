# KHDiamond Stremio & Nuvio Addon

Production-grade Stremio addon providing Khmer-dubbed movies and series directly from `khdiamond.net` with ultra-fast CDN delivery and native HLS stream proxying.

## Architecture

- **Direct Proxy Transport**: Routes network traffic through Cambodia residential/datacenter proxy (`socks5://100.108.63.53:1080`), bypassing Cloudflare challenges with sub-200ms latency.
- **Dynamic Authentication Session**: Automatically signs in to `khdiamond.net` via `dooplay_login`, maintaining and auto-refreshing authenticated session cookies.
- **Dual Catalogs**:
  - Movies: `khd_movies` (`/movies/page/:p/`)
  - Series: `khd_series` (`/tvshows/page/:p/`)
  - Search & Pagination supported.
- **Metadata Resolver**: Full title, synopsis, poster, background, genres, release year, and complete episode trees (`#seasons a[href*="/episodes/"]`).
- **Universal Stream Resolution**:
  - Resolves internal `khd:` IDs (Movies & Series).
  - Resolves IMDb (`tt...`) and TMDb (`tmdb:...`) IDs via Cinemeta / TMDb integration with canonical Khmer dub title matching.
- **Signed HLS Proxy Engine**:
  - Dynamically rewrites master and rendition `.m3u8` playlists with HMAC-SHA256 signatures.
  - Automatically injects `X-Stream-Token`, `Cookie`, and `Referer` headers for playlist authorization.
  - Passes open CDN segment chunks (`media-1.khdmcloud.online`) directly to video players (ExoPlayer, VLC, iOS, Web) for high-speed playback with zero server bandwidth load.

## Quick Start

### 1. Environment Configuration

Edit or review `.env`:

```env
PORT=7070
SITE_URL=https://khdiamond.net
CAMBODIA_PROXY=socks5://100.108.63.53:1080
KHDIAMOND_USER=chumlayan95@gmail.com
KHDIAMOND_PASS=240995L@yan
CACHE_TTL_S=3600
PROXY_SECRET=khdiamond_secret_2026
```

### 2. Run Verification Test Suite

```bash
cd /home/ubuntu/khdiamond-stremio-addon
node test.js
```

### 3. Manage with PM2

```bash
pm2 start ecosystem.config.js
pm2 restart khdiamond-addon
pm2 status
```

## Multi-User Setup

Connect individual KHDiamond accounts with 1 click:
1. Open `http://<host>:7070/configure` (or `http://100.99.23.40:7070/configure` over Tailscale).
2. Enter your KHDiamond.net email & password.
3. The addon authenticates through the Cambodia proxy in <300ms, detects your purchased movies, and generates your personal Stremio/Nuvio TV addon link (`/u/<token>/manifest.json`).

## Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Web landing page |
| `GET /configure` | Multi-user self-service setup page |
| `POST /api/register` | User authentication & personal token generation API |
| `GET /manifest.json` | Default shared Stremio manifest |
| `GET /u/:token/manifest.json` | User-scoped personal manifest (includes purchased `khd_unlocked` library) |
| `GET /u/:token/catalog/:type/:id/:extra?.json` | User-scoped catalog browsing |
| `GET /u/:token/stream/:type/:id.json` | User-scoped stream resolution |
| `GET /proxy/hls/master.m3u8` | Signed real-time HLS master playlist proxy |
| `GET /proxy/hls/playlist.m3u8` | Signed sub-playlist rewrite for open CDN chunk playback |
| `GET /proxy/hls/master.m3u8` | Signed master playlist proxy |
| `GET /proxy/hls/playlist.m3u8` | Signed sub-playlist rendition proxy |
| `GET /health` | Health and uptime monitor |
