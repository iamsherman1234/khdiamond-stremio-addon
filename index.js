"use strict";

require("dotenv").config();
const express = require("express");
const cors = require("cors");
const manifest = require("./manifest");
const { FlareSolverrClient } = require("./lib/flaresolverr");
const { KhdiamondScraper } = require("./lib/scraper");

const app = express();
const PORT = parseInt(process.env.PORT || "7070", 10);

app.use(cors());
app.use(express.json());

// Initialize FlareSolverr & Scraper
const flaresolverr = new FlareSolverrClient();
const scraper = new KhdiamondScraper(flaresolverr);

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

// ── 0. LANDING & HEALTH CHECK ──
app.get("/", (req, res) => {
  const host = req.get("host");
  const protocol = req.protocol;
  const manifestUrl = `${protocol}://${host}/manifest.json`;
  const installUrl = `stremio://${host}/manifest.json`;

  res.send(`
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>${manifest.name}</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .box { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 32px; max-width: 480px; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
        h1 { color: #58a6ff; margin-bottom: 8px; font-size: 24px; }
        p { color: #8b949e; font-size: 14px; margin-bottom: 24px; line-height: 1.5; }
        .btn { display: inline-block; background: #238636; color: #fff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; transition: background 0.2s; }
        .btn:hover { background: #2ea043; }
        .code { background: #0d1117; padding: 8px 12px; border-radius: 6px; font-family: monospace; font-size: 12px; word-break: break-all; margin-top: 16px; border: 1px solid #30363d; }
      </style>
    </head>
    <body>
      <div class="box">
        <h1>${manifest.name}</h1>
        <p>${manifest.description}</p>
        <a class="btn" href="${installUrl}">Install to Stremio</a>
        <div class="code">Manifest: ${manifestUrl}</div>
      </div>
    </body>
    </html>
  `);
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
    const metas = await scraper.getCatalog(type, {
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
  console.log(`[Addon] Stream request: type=${type}, id=${id}`);

  try {
    const streams = await scraper.getStreams(type, id);
    res.setHeader("Cache-Control", "max-age=1800, public");
    res.json({ streams });
  } catch (err) {
    console.error("[Addon] Stream error:", err.message);
    res.json({ streams: [] });
  }
});

app.listen(PORT, () => {
  console.log(`[Addon] KHDiamond Stremio addon running at http://localhost:${PORT}`);
  console.log(`[Addon] Manifest URL: http://localhost:${PORT}/manifest.json`);
});
