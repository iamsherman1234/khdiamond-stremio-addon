"use strict";

require("dotenv").config();
const express = require("express");
const cors = require("cors");
const manifest = require("./manifest");
const { HttpClient } = require("./lib/client");
const { HlsProxy } = require("./lib/hlsProxy");
const { KhdiamondScraper } = require("./lib/scraper");
const { UserManager } = require("./lib/userManager");

const app = express();
const PORT = parseInt(process.env.PORT || "7070", 10);

app.use(cors({
  origin: "*",
  methods: ["GET", "POST", "OPTIONS"],
  allowedHeaders: ["Content-Type", "Authorization", "Range", "X-Requested-With"]
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Initialize Core Instances
const defaultHttpClient = new HttpClient();
const hlsProxy = new HlsProxy({ httpClient: defaultHttpClient });
const userManager = new UserManager({
  defaultClient: defaultHttpClient,
  hlsProxy: hlsProxy,
  secret: process.env.ADDON_SECRET || process.env.PROXY_SECRET,
});
hlsProxy.setUserManager(userManager);

const defaultScraper = userManager.getScraper("");

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
    if (req.path.includes("/stream/") || req.path.includes("/catalog/") || req.path.includes("/meta/")) {
      console.log(`[HTTP] ${req.method} ${req.path} -> ${res.statusCode} (${duration}ms)`);
    }
  });
  next();
});

// ── 0. CONFIGURE & LANDING PAGES ──
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
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #c9d1d9; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .box { background: #161b26; border: 1px solid #283044; border-radius: 16px; padding: 40px; max-width: 540px; width: 100%; text-align: center; box-shadow: 0 16px 40px rgba(0,0,0,0.6); }
        .logo { width: 96px; height: 96px; border-radius: 20px; margin-bottom: 20px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
        h1 { color: #58a6ff; margin: 0 0 12px; font-size: 26px; }
        p { color: #8b949e; font-size: 15px; margin: 0 0 24px; line-height: 1.6; }
        .badges { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-bottom: 28px; }
        .badge { background: #1f2638; border: 1px solid #323d57; padding: 5px 12px; border-radius: 20px; font-size: 12px; color: #79c0ff; font-weight: 500; }
        .btn-group { display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }
        .btn { display: block; text-decoration: none; padding: 14px 24px; border-radius: 10px; font-weight: 600; font-size: 15px; transition: transform 0.15s, background 0.2s; }
        .btn-primary { background: #238636; color: #fff; box-shadow: 0 4px 14px rgba(35,134,54,0.3); }
        .btn-primary:hover { background: #2ea043; transform: translateY(-1px); }
        .btn-secondary { background: #1f293d; color: #58a6ff; border: 1px solid #384566; }
        .btn-secondary:hover { background: #28354f; }
        .code { background: #0d111a; padding: 12px 14px; border-radius: 8px; font-family: monospace; font-size: 13px; word-break: break-all; border: 1px solid #283044; color: #79c0ff; text-align: left; }
      </style>
    </head>
    <body>
      <div class="box">
        <img class="logo" src="${manifest.logo}" alt="KHDiamond Logo">
        <h1>${manifest.name}</h1>
        <p>${manifest.description}</p>
        <div class="badges">
          <span class="badge">🇰🇭 Khmer Dubbed</span>
          <span class="badge">👥 Multi-User Support</span>
          <span class="badge">⚡ Fast Open CDN</span>
          <span class="badge">🎬 1080p Trailers</span>
        </div>
        <div class="btn-group">
          <a class="btn btn-primary" href="/configure">⚙️ Connect Personal KHDiamond Account</a>
          <a class="btn btn-secondary" href="${installUrl}">⚡ Install Default Shared Addon</a>
        </div>
        <div class="code">${manifestUrl}</div>
      </div>
    </body>
    </html>
  `);
});

app.get("/configure", (req, res) => {
  const hostBase = getHostBase(req);

  res.send(`
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Configure KHDiamond Addon</title>
      <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #c9d1d9; display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
        .card { background: #161b26; border: 1px solid #283044; border-radius: 16px; padding: 36px; max-width: 520px; width: 100%; box-shadow: 0 16px 40px rgba(0,0,0,0.6); }
        .header { text-align: center; margin-bottom: 28px; }
        .logo { width: 80px; height: 80px; border-radius: 16px; margin-bottom: 16px; box-shadow: 0 6px 18px rgba(0,0,0,0.4); }
        h1 { color: #58a6ff; font-size: 24px; margin-bottom: 8px; }
        .sub { color: #8b949e; font-size: 14px; line-height: 1.5; }
        .form-group { margin-bottom: 18px; text-align: left; }
        label { display: block; font-size: 13px; font-weight: 600; color: #8b949e; margin-bottom: 6px; }
        input { width: 100%; padding: 12px 14px; background: #0d111a; border: 1px solid #30363d; border-radius: 8px; color: #f0f6fc; font-size: 15px; outline: none; transition: border 0.2s; }
        input:focus { border-color: #58a6ff; }
        .btn-submit { width: 100%; padding: 14px; background: #238636; color: #fff; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; margin-top: 8px; }
        .btn-submit:hover { background: #2ea043; }
        .btn-submit:disabled { background: #21262d; color: #6e7681; cursor: not-allowed; }
        .alert { display: none; padding: 14px; border-radius: 8px; font-size: 14px; margin-top: 18px; line-height: 1.4; }
        .alert-error { background: #3d1214; border: 1px solid #8e1c1f; color: #ff7b72; }
        .alert-success { background: #0f2d1a; border: 1px solid #1f6feb; color: #7ee787; }
        .result-box { display: none; margin-top: 24px; border-top: 1px solid #283044; padding-top: 24px; text-align: left; }
        .stat-badge { display: inline-block; background: #1f2638; border: 1px solid #384566; padding: 4px 10px; border-radius: 12px; font-size: 12px; color: #79c0ff; margin-bottom: 16px; }
        .install-btn { display: block; text-align: center; background: #1f6feb; color: #fff; text-decoration: none; padding: 14px; border-radius: 8px; font-weight: 600; font-size: 15px; margin-bottom: 14px; transition: background 0.2s; }
        .install-btn:hover { background: #388bfd; }
        .url-box { background: #0d111a; border: 1px solid #30363d; border-radius: 8px; padding: 10px 12px; font-family: monospace; font-size: 12px; color: #79c0ff; word-break: break-all; margin-bottom: 12px; }
        .copy-btn { background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; width: 100%; transition: background 0.2s; }
        .copy-btn:hover { background: #30363d; }
        .nuvio-tip { margin-top: 18px; padding: 12px; background: #121824; border-radius: 8px; font-size: 13px; color: #8b949e; line-height: 1.5; }
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <img class="logo" src="${manifest.logo}" alt="Logo">
          <h1>KHDiamond Personal Setup</h1>
          <p class="sub">Log in with your KHDiamond.net account to stream all your purchased movies and watch trailers in Stremio / Nuvio TV.</p>
        </div>

        <form id="loginForm">
          <div class="form-group">
            <label for="username">KHDiamond Email / Username</label>
            <input type="text" id="username" name="username" placeholder="user@gmail.com" required autocomplete="username">
          </div>
          <div class="form-group">
            <label for="password">KHDiamond Password</label>
            <input type="password" id="password" name="password" placeholder="••••••••" required autocomplete="current-password">
          </div>
          <button type="submit" id="submitBtn" class="btn-submit">Connect Account & Generate Addon</button>
        </form>

        <div id="statusAlert" class="alert"></div>

        <div id="resultBox" class="result-box">
          <div id="statBadge" class="stat-badge"></div>
          <a id="stremioBtn" class="install-btn" href="#">⚡ Install to Stremio</a>
          <label style="font-size:12px; margin-bottom:4px; display:block;">Addon Manifest URL (for Nuvio TV / Web):</label>
          <div id="manifestUrlText" class="url-box"></div>
          <button id="copyBtn" class="copy-btn" onclick="copyUrl()">📋 Copy Manifest URL</button>

          <div class="nuvio-tip">
            📺 <strong>For Nuvio TV / Android TV:</strong><br>
            Open Nuvio TV Settings &rarr; Addons &rarr; <em>Add by URL</em>, then paste the copied Manifest URL above.
          </div>
        </div>
      </div>

      <script>
        const form = document.getElementById("loginForm");
        const submitBtn = document.getElementById("submitBtn");
        const alertBox = document.getElementById("statusAlert");
        const resultBox = document.getElementById("resultBox");
        const statBadge = document.getElementById("statBadge");
        const stremioBtn = document.getElementById("stremioBtn");
        const manifestUrlText = document.getElementById("manifestUrlText");
        const hostBase = "${hostBase}";

        form.addEventListener("submit", async (e) => {
          e.preventDefault();
          submitBtn.disabled = true;
          submitBtn.textContent = "Connecting via Cambodia Proxy...";
          alertBox.style.display = "none";
          resultBox.style.display = "none";

          const username = document.getElementById("username").value.trim();
          const password = document.getElementById("password").value.trim();

          try {
            const res = await fetch("/api/register", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ username, password })
            });

            const data = await res.json();
            if (!res.ok || !data.success) {
              throw new Error(data.error || "Login verification failed");
            }

            const manifestUrl = hostBase + "/u/" + data.token + "/manifest.json";
            const installUrl = "stremio://" + hostBase.replace(/^https?:\\/\\//, "") + "/u/" + data.token + "/manifest.json";

            statBadge.textContent = "👤 " + data.username + " • " + (data.unlockedCount || 0) + " Purchased Movies Unlocked";
            stremioBtn.href = installUrl;
            manifestUrlText.textContent = manifestUrl;
            resultBox.style.display = "block";

            alertBox.className = "alert alert-success";
            alertBox.textContent = "✅ Connected successfully! Your personal addon is ready.";
            alertBox.style.display = "block";
          } catch (err) {
            alertBox.className = "alert alert-error";
            alertBox.textContent = "❌ " + err.message;
            alertBox.style.display = "block";
          } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = "Connect Account & Generate Addon";
          }
        });

        function copyUrl() {
          const text = manifestUrlText.textContent;
          navigator.clipboard.writeText(text).then(() => {
            const btn = document.getElementById("copyBtn");
            btn.textContent = "✅ Copied to Clipboard!";
            setTimeout(() => { btn.textContent = "📋 Copy Manifest URL"; }, 2500);
          });
        }
      </script>
    </body>
    </html>
  `);
});

// ── API: REGISTER / LOGIN USER ──
app.post("/api/register", async (req, res) => {
  const { username, password } = req.body;
  if (!username || !password) {
    return res.status(400).json({ success: false, error: "Username and password required" });
  }

  try {
    const userResult = await userManager.registerUser(username, password);
    const hostBase = getHostBase(req);
    const manifestUrl = `${hostBase}/u/${userResult.token}/manifest.json`;

    res.json({
      success: true,
      token: userResult.token,
      username: userResult.username,
      unlockedCount: userResult.unlockedCount,
      manifestUrl,
    });
  } catch (err) {
    console.error("[API] Registration error:", err.message);
    res.status(401).json({ success: false, error: err.message });
  }
});

// ── API: LIST USERS (ADMIN/STATUS) ──
app.get("/api/users", (req, res) => {
  const users = userManager.listUsers();
  res.json({ count: users.length, users });
});

app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    addon: manifest.id,
    version: manifest.version,
    usersCount: userManager.listUsers().length,
    uptime: Math.floor(process.uptime()),
    timestamp: new Date().toISOString()
  });
});

// ══════════════════════════════════════════════════════════════════
// ── USER-SCOPED ROUTES (/u/:token/...) ──
// ══════════════════════════════════════════════════════════════════

// 1. User Manifest
app.get("/u/:token/manifest.json", (req, res) => {
  const { token } = req.params;
  const user = userManager.getUser(token);
  if (!user) {
    return res.status(404).json({ error: "User token not found" });
  }

  const shortName = user.username.split("@")[0];
  const userManifest = {
    ...manifest,
    id: `org.khdiamond.addon.${token}`,
    name: `KHDiamond [${shortName}]`,
    description: `Khmer dubbed movies, series & trailers for ${user.username} (${user.unlockedCount || 0} unlocked titles)`
  };

  res.setHeader("Cache-Control", "max-age=86400, public");
  res.json(userManifest);
});

// 2. User Catalog
app.get("/u/:token/catalog/:type/:id/:extra?.json", async (req, res) => {
  const { token, type, id } = req.params;
  const extra = parseExtra(req.params.extra);
  const user = userManager.getUser(token);
  if (!user) {
    return res.status(404).json({ error: "User token not found" });
  }

  console.log(`[UserAddon:${token}] Catalog request: type=${type}, id=${id}, extra=`, extra);

  try {
    const userScraper = userManager.getScraper(token);
    const metas = await userScraper.getCatalog(type, id, {
      search: extra.search,
      skip: parseInt(extra.skip || "0", 10),
    });
    res.setHeader("Cache-Control", "max-age=1800, public");
    res.json({ metas });
  } catch (err) {
    console.error(`[UserAddon:${token}] Catalog error:`, err.message);
    res.json({ metas: [] });
  }
});

// 3. User Meta
app.get("/u/:token/meta/:type/:id.json", async (req, res) => {
  const { token, type, id } = req.params;
  const user = userManager.getUser(token);
  if (!user) {
    return res.status(404).json({ error: "User token not found" });
  }

  console.log(`[UserAddon:${token}] Meta request: type=${type}, id=${id}`);

  try {
    const userScraper = userManager.getScraper(token);
    const meta = await userScraper.getMeta(type, id);
    res.setHeader("Cache-Control", "max-age=3600, public");
    res.json({ meta });
  } catch (err) {
    console.error(`[UserAddon:${token}] Meta error:`, err.message);
    res.status(500).json({ error: err.message });
  }
});

// 4. User Stream
app.get("/u/:token/stream/:type/:id.json", async (req, res) => {
  const { token, type, id } = req.params;
  const cleanId = id.replace(/\.json$/, "");
  const hostBase = getHostBase(req);
  const user = userManager.getUser(token);
  if (!user) {
    return res.status(404).json({ error: "User token not found" });
  }

  console.log(`[UserAddon:${token}] Stream request: type=${type}, id=${cleanId}`);

  try {
    const userScraper = userManager.getScraper(token);
    const streams = await userScraper.getStreams(type, cleanId, hostBase);
    res.setHeader("Cache-Control", "max-age=1800, public");
    res.json({ streams });
  } catch (err) {
    console.error(`[UserAddon:${token}] Stream error:`, err.message);
    res.json({ streams: [] });
  }
});

// ══════════════════════════════════════════════════════════════════
// ── DEFAULT / SHARED ROUTES (Single-tenant fallback) ──
// ══════════════════════════════════════════════════════════════════

// 1. MANIFEST
app.get("/manifest.json", (req, res) => {
  res.setHeader("Cache-Control", "max-age=86400, public");
  res.json(manifest);
});

// 2. CATALOG
app.get("/catalog/:type/:id/:extra?.json", async (req, res) => {
  const { type, id } = req.params;
  const extra = parseExtra(req.params.extra);

  console.log(`[Addon] Catalog request: type=${type}, id=${id}, extra=`, extra);

  try {
    const metas = await defaultScraper.getCatalog(type, id, {
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

// 3. META
app.get("/meta/:type/:id.json", async (req, res) => {
  const { type, id } = req.params;
  console.log(`[Addon] Meta request: type=${type}, id=${id}`);

  try {
    const meta = await defaultScraper.getMeta(type, id);
    res.setHeader("Cache-Control", "max-age=3600, public");
    res.json({ meta });
  } catch (err) {
    console.error("[Addon] Meta error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// 4. STREAM
app.get("/stream/:type/:id.json", async (req, res) => {
  const { type, id } = req.params;
  const cleanId = id.replace(/\.json$/, "");
  const hostBase = getHostBase(req);

  console.log(`[Addon] Stream request: type=${type}, id=${cleanId}`);

  try {
    const streams = await defaultScraper.getStreams(type, cleanId, hostBase);
    res.setHeader("Cache-Control", "max-age=1800, public");
    res.json({ streams });
  } catch (err) {
    console.error("[Addon] Stream error:", err.message);
    res.json({ streams: [] });
  }
});

// ── 5. HLS PROXY ROUTES (Handles both default & user-scoped tokens) ──
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
  console.log(`[Addon] Default Manifest: http://localhost:${PORT}/manifest.json`);
  console.log(`[Addon] Multi-User Configure: http://localhost:${PORT}/configure`);
});
