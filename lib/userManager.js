"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const cheerio = require("cheerio");
const { HttpClient } = require("./client");
const { KhdiamondScraper } = require("./scraper");

class UserManager {
  constructor(options = {}) {
    this.dataDir = options.dataDir || path.join(__dirname, "..", "data");
    this.usersFile = path.join(this.dataDir, "users.json");
    this.secret = (options.secret || process.env.PROXY_SECRET || process.env.ADDON_SECRET || "khdiamond_secret_2026").trim();
    this.defaultClient = options.defaultClient || new HttpClient();
    this.hlsProxy = options.hlsProxy || null;

    this.users = {};
    this.clientPool = new Map();
    this.scraperPool = new Map();

    this._init();
  }

  _init() {
    try {
      if (!fs.existsSync(this.dataDir)) {
        fs.mkdirSync(this.dataDir, { recursive: true });
      }
      if (fs.existsSync(this.usersFile)) {
        const raw = fs.readFileSync(this.usersFile, "utf8");
        const parsed = JSON.parse(raw);
        this.users = parsed.users || {};
      } else {
        this.users = {};
        this._save();
      }
    } catch (err) {
      console.error("[UserManager] Failed to load users.json:", err.message);
      this.users = {};
    }
  }

  _save() {
    try {
      fs.writeFileSync(this.usersFile, JSON.stringify({ users: this.users, updatedAt: new Date().toISOString() }, null, 2), "utf8");
    } catch (err) {
      console.error("[UserManager] Failed to write users.json:", err.message);
    }
  }

  _getKey() {
    return crypto.scryptSync(this.secret, "khd_user_salt", 32);
  }

  encrypt(text) {
    if (!text) return "";
    const key = this._getKey();
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
    let enc = cipher.update(text, "utf8", "hex");
    enc += cipher.final("hex");
    const tag = cipher.getAuthTag().toString("hex");
    return `${iv.toString("hex")}:${tag}:${enc}`;
  }

  decrypt(payload) {
    if (!payload || !payload.includes(":")) return "";
    try {
      const [ivHex, tagHex, dataHex] = payload.split(":");
      const key = this._getKey();
      const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(ivHex, "hex"));
      decipher.setAuthTag(Buffer.from(tagHex, "hex"));
      let dec = decipher.update(dataHex, "hex", "utf8");
      dec += decipher.final("utf8");
      return dec;
    } catch {
      return "";
    }
  }

  async registerUser(username, password) {
    const cleanUser = String(username || "").trim();
    const cleanPass = String(password || "").trim();

    if (!cleanUser || !cleanPass) {
      throw new Error("Username and password are required");
    }

    // Authenticate through Cambodia proxy or FlareSolverr clearance
    const tempClient = new HttpClient({
      user: cleanUser,
      pass: cleanPass,
      proxyUrl: this.defaultClient.proxyUrl,
      siteUrl: this.defaultClient.siteUrl,
      flaresolverr: this.defaultClient.flaresolverr,
    });

    const cookie = await tempClient.login(cleanUser, cleanPass);
    if (!cookie) {
      throw new Error("Invalid KHDiamond credentials or login failed");
    }

    // Inspect user purchases on /my-account/
    let unlockedCount = 0;
    try {
      const acctRes = await tempClient.get(`${tempClient.siteUrl}/my-account/`);
      const $ = cheerio.load(acctRes.html);
      const orderCountText = $(".kd-value").first().text().trim();
      const orderCount = parseInt(orderCountText, 10);
      if (!isNaN(orderCount) && orderCount > 0) {
        unlockedCount = orderCount;
      } else {
        const mCount = parseInt($("#filter_items_movie small").text().trim(), 10) || 0;
        const sMatch = $("#filter_items_tvshows small").text().match(/(\d+)\s*ភាគ/);
        const sCount = sMatch ? parseInt(sMatch[1], 10) : 0;
        unlockedCount = (mCount + sCount) || $("#items_movies article").length;
      }
    } catch (err) {
      console.warn("[UserManager] Could not parse purchased count:", err.message);
    }

    // Check if user already exists
    let existingToken = null;
    for (const [t, u] of Object.entries(this.users)) {
      if (u.username.toLowerCase() === cleanUser.toLowerCase()) {
        existingToken = t;
        break;
      }
    }

    const token = existingToken || crypto.randomBytes(8).toString("hex");
    const now = new Date().toISOString();

    this.users[token] = {
      token,
      username: cleanUser,
      password: this.encrypt(cleanPass),
      cookie: cookie,
      unlockedCount,
      created: existingToken ? (this.users[token].created || now) : now,
      lastLogin: now,
    };

    this._save();

    // Cache active client in pool
    this.clientPool.set(token, tempClient);
    if (this.hlsProxy) {
      this.scraperPool.set(token, new KhdiamondScraper(tempClient, this.hlsProxy, token));
    }

    console.log(`[UserManager] Registered user '${cleanUser}' (token: ${token}, purchases: ${unlockedCount})`);

    return {
      token,
      username: cleanUser,
      unlockedCount,
      isNew: !existingToken,
    };
  }

  getUser(token) {
    if (!token || !this.users[token]) return null;
    const u = this.users[token];
    return {
      token: u.token,
      username: u.username,
      unlockedCount: u.unlockedCount || 0,
      created: u.created,
      lastLogin: u.lastLogin,
    };
  }

  getClient(token) {
    if (!token) return this.defaultClient;

    if (this.clientPool.has(token)) {
      return this.clientPool.get(token);
    }

    const u = this.users[token];
    if (!u) return this.defaultClient;

    const pass = this.decrypt(u.password);
    const client = new HttpClient({
      user: u.username,
      pass,
      proxyUrl: this.defaultClient.proxyUrl,
      siteUrl: this.defaultClient.siteUrl,
      flaresolverr: this.defaultClient.flaresolverr,
      cachedCookie: u.cookie || null,
    });

    this.clientPool.set(token, client);
    return client;
  }

  getScraper(token) {
    if (!token) {
      if (!this.defaultScraper && this.hlsProxy) {
        this.defaultScraper = new KhdiamondScraper(this.defaultClient, this.hlsProxy, "");
      }
      return this.defaultScraper;
    }

    if (this.scraperPool.has(token)) {
      return this.scraperPool.get(token);
    }

    const client = this.getClient(token);
    const scraper = new KhdiamondScraper(client, this.hlsProxy, token);
    this.scraperPool.set(token, scraper);
    return scraper;
  }

  listUsers() {
    return Object.values(this.users).map((u) => ({
      token: u.token,
      username: u.username,
      unlockedCount: u.unlockedCount || 0,
      created: u.created,
      lastLogin: u.lastLogin,
    }));
  }

  deleteUser(token) {
    if (this.users[token]) {
      delete this.users[token];
      this.clientPool.delete(token);
      this.scraperPool.delete(token);
      this._save();
      return true;
    }
    return false;
  }
}

module.exports = { UserManager };
