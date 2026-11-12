"use strict";

require("dotenv").config();
const express = require("express");
const cors = require("cors");
const manifest = require("./manifest");
const { HttpClient } = require("./lib/client");
const { HlsProxy } = require("./lib/hlsProxy");
const { KhdiamondScraper } = require("./lib/scraper");

const app = express();
const PORT = parseInt(process.env.PORT || "7070", 10);

app.use(cors({
  origin: "*",
  methods: ["GET", "POST", "OPTIONS"],
  allowedHeaders: ["Content-Type", "Authorization", "Range", "X-Requested-With"]
}));

app.use(express.json());

// Initialize Client, Proxy & Scraper
const httpClient = new HttpClient();
const hlsProxy = new HlsProxy({ httpClient });
const scraper = new KhdiamondScraper(httpClient, hlsProxy);

function getHostBase(req) {
  if (process.env.PUBLIC_URL) {
    return process.env.PUBLIC_URL.replace(/\/+$/, "");
  }
  const proto = req.headers["x-forwarded-proto"] || req.protocol || "http";
  const host = req.headers["x-forwarded-host"] || req.get("host") || `localhost:${PORT}`;
  return `${proto}://${host}`;
}

function parseExtra(extraStr) {
  if (!extraStr) return {};
  const extra = {};
  const pairs = extraStr.split("&");
  for (const pair of pairs) {
    const [k, v] = pair.split("=");
    if (k && v) {
      extra[decodeURIComponent(k)] = decodeURIComponent(v);
    }
  }
  return extra;
}

// ── REQUEST LOGGER ──
app.use((req, res, next) => {
  const start = Date.now();
  res.on("finish", () => {
    const duration = Date.now() - start;
    if (req.path.startsWith("/stream/") || req.path.startsWith("/catalog/") || req.path.startsWith("/meta/")) {
      console.log(`[HTTP] ${req.method} ${req.path} -> ${res.statusCode} (${duration}ms)`);
    }
  });
  next();
});

// ── 0. LANDING & HEALTH CHECK ──
app.get("/", (req, res) => {
  const hostBase = getHostBase(req);
  const manifestUrl = `${hostBase}/manifest.json`;
  const installUrl = `stremio://${hostBase.replace(/^https?:\/\//, "")}/manifest.json`;

  res.send(`
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>${manifest.name}</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .box { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 36px; max-width: 520px; width: 100%; text-align: center; box-shadow: 0 12px 32px rgba(0,0,0,0.6); }
        .logo { width: 96px; height: 96px; border-radius: 16px; margin-bottom: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
        h1 { color: #58a6ff; margin: 0 0 12px; font-size: 26px; }
        p { color: #8b949e; font-size: 15px; margin: 0 0 24px; line-height: 1.6; }
        .badges { display: flex; gap: 8px; justify-content: center; margin-bottom: 24px; }
        .badge { background: #21262d; border: 1px solid #30363d; padding: 4px 10px; border-radius: 20px; font-size: 12px; color: #58a6ff; }
        .btn { display: inline-block; background: #238636; color: #fff; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-weight: 600; font-size: 16px; transition: background 0.2s; box-shadow: 0 4px 12px rgba(35,134,54,0.3); }
        .btn:hover { background: #2ea043; }
        .code { background: #0d1117; padding: 12px 14px; border-radius: 8px; font-family: monospace; font-size: 13px; word-break: break-all; margin-top: 24px; border: 1px solid #30363d; color: #79c0ff; }
      </style>
    </head>
    <body>
      <div class="box">
        <img class="logo" src="${manifest.logo}" alt="KHDiamond Logo">
        <h1>${manifest.name}</h1>
        <p>${manifest.description}</p>
        <div class="badges">
          <span class="badge">🇰🇭 Khmer Dubbed</span>
          <span class="badge">⚡ Fast CDN</span>
          <span class="badge">📺 Movies & Series</span>
        </div>
        <a class="btn" href="${installUrl}">Install to Stremio</a>
        <div class="code">${manifestUrl}</div>
      </div>
    </body>
    </html>
  `);
});

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    addon: manifest.id,
    version: manifest.version,
    uptime: Math.floor(process.uptime()),
    timestamp: new Date().toISOString()
  });
});

// ── 1. MANIFEST ──
app.get("/manifest.json", (req, res) => {
  res.setHeader("Cache-Control", "max-age=86400, public");
  res.json(manifest);
});

// ── 2. CATALOG ──
app.get("/catalog/:type/:id/:extra?.json", async (req, res) => {
  const { type, id } = req.params;
  const extra = parseExtra(req.params.extra);

  console.log(`[Addon] Catalog request: type=${type}, id=${id}, extra=`, extra);

  try {
    const metas = await scraper.getCatalog(type, id, {
      search: extra.search,
      skip: parseInt(extra.skip || "0", 10),
    });
    res.setHeader("Cache-Control", "max-age=1800, public");
    res.json({ metas });
  } catch (err) {
    console.error("[Addon] Catalog error:", err.message);
    res.json({ metas: [] });
  }
});

// ── 3. META ──
app.get("/meta/:type/:id.json", async (req, res) => {
  const { type, id } = req.params;
  console.log(`[Addon] Meta request: type=${type}, id=${id}`);

  try {
    const meta = await scraper.getMeta(type, id);
    res.setHeader("Cache-Control", "max-age=3600, public");
    res.json({ meta });
  } catch (err) {
    console.error("[Addon] Meta error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ── 4. STREAM ──
app.get("/stream/:type/:id.json", async (req, res) => {
  const { type, id } = req.params;
  const cleanId = id.replace(/\.json$/, "");
  const hostBase = getHostBase(req);

  console.log(`[Addon] Stream request: type=${type}, id=${cleanId}`);

  try {
    const streams = await scraper.getStreams(type, cleanId, hostBase);
    res.setHeader("Cache-Control", "max-age=1800, public");
    res.json({ streams });
  } catch (err) {
    console.error("[Addon] Stream error:", err.message);
    res.json({ streams: [] });
  }
});

// ── 5. HLS PROXY ROUTES ──
app.get("/proxy/hls/master.m3u8", async (req, res) => {
  const hostBase = getHostBase(req);
  await hlsProxy.handleMasterPlaylist(req, res, hostBase);
});

app.get("/proxy/hls/playlist.m3u8", async (req, res) => {
  const hostBase = getHostBase(req);
  await hlsProxy.handleSubPlaylist(req, res, hostBase);
});

app.listen(PORT, () => {
  console.log(`[Addon] KHDiamond Stremio addon running at http://localhost:${PORT}`);
  console.log(`[Addon] Manifest URL: http://localhost:${PORT}/manifest.json`);
});
