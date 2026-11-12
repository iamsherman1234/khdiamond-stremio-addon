# KHDiamond Stremio / Nuvio Addon

Scrapes Khmer-dubbed movies and series from `khdiamond.net` through a FlareSolverr challenge solver, resolving direct streams and serving them via the Stremio Addon HTTP protocol.

## Features

- **Catalog**: Browse Movies (`khd_movies`) and Series (`khd_series`) with search support.
- **Metadata**: Posters, titles, synopses, genres, and series episode lists.
- **Streams**: Extracts direct HLS (`.m3u8`), MP4, Pixeldrain, and embedded player streams.
- **Cloudflare Bypass**: Routes requests through FlareSolverr `/v1` endpoint to pass Turnstile challenges and maintain session cookies.
- **Caching**: In-memory caching for catalogs, meta, and streams to optimize response time.

## Quick Start

### 1. Configure Environment

Review or edit `.env`:

```env
PORT=7070
SITE_URL=https://khdiamond.net
FLARESOLVERR_URL=https://trawl.sudolocal.qzz.io/v1
FLARESOLVERR_TIMEOUT=60000
CACHE_TTL_S=3600
COOKIES='[{"name":"user_login_ses_hash","value":"...","domain":"khdiamond.net"},...]'
```

### 2. Test Scraper Pipeline

Run the verification test:

```bash
cd /home/ubuntu/khdiamond-stremio-addon
node test.js
```

### 3. Run the Server

```bash
# Direct run
node index.js

# Or with PM2
pm2 start ecosystem.config.js
```

### 4. Install into Stremio / Nuvio

- Manifest URL: `http://<your-host>:7070/manifest.json`
- In Stremio: Paste the manifest URL into the search/addon bar or visit `http://<your-host>:7070/` in your browser and click **Install to Stremio**.
