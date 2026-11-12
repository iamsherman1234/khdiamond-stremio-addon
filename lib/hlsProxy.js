"use strict";

const crypto = require("crypto");

class HlsProxy {
  constructor(options = {}) {
    this.secret = (options.secret || process.env.PROXY_SECRET || "khdiamond_secret_2026").trim();
    this.httpClient = options.httpClient;
    this.siteUrl = (options.siteUrl || process.env.SITE_URL || "https://khdiamond.net").replace(/\/+$/, "");
  }

  sign(data) {
    return crypto.createHmac("sha256", this.secret).update(String(data)).digest("hex").slice(0, 16);
  }

  verify(data, signature) {
    if (!signature || typeof signature !== "string") return false;
    const expected = this.sign(data);
    return signature.length === expected.length && crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  }

  buildOnDemandStreamUrl(serverBase, pageUrl, post, nume, type) {
    const cleanBase = (serverBase || "").replace(/\/+$/, "");
    const encPage = Buffer.from(pageUrl).toString("base64url");
    const sig = this.sign(`ondemand:${post}:${nume}:${type}:${pageUrl}`);

    return `${cleanBase}/proxy/hls/master.m3u8?p=${post}&n=${nume}&ty=${type}&r=${encPage}&s=${sig}`;
  }

  buildProxyUrl(serverBase, masterUrl, streamToken, embedUrl) {
    const cleanBase = (serverBase || "").replace(/\/+$/, "");
    const encodedTarget = Buffer.from(masterUrl).toString("base64url");
    const encodedToken = Buffer.from(streamToken || "").toString("base64url");
    const encodedRef = Buffer.from(embedUrl || "").toString("base64url");
    const sig = this.sign(`${masterUrl}:${streamToken}`);

    return `${cleanBase}/proxy/hls/master.m3u8?t=${encodedTarget}&k=${encodedToken}&r=${encodedRef}&s=${sig}`;
  }

  async handleMasterPlaylist(req, res, serverBase) {
    const { p, n, ty, t, k, r, s } = req.query;

    // ── MODE A: ON-DEMAND REAL-TIME TOKEN RESOLUTION ──
    if (p && n && ty && r && s) {
      let pageUrl;
      try {
        pageUrl = Buffer.from(r, "base64url").toString("utf8");
      } catch {
        return res.status(400).send("Invalid ref encoding");
      }

      if (!this.verify(`ondemand:${p}:${n}:${ty}:${pageUrl}`, s)) {
        return res.status(403).send("Invalid signature");
      }

      try {
        // 1. Fetch target page to get active nonce
        const pageRes = await this.httpClient.get(pageUrl);
        const nonceMatch = pageRes.html.match(/"nonce"\s*:\s*"([a-f0-9]+)"/i);
        const nonce = nonceMatch ? nonceMatch[1] : "";

        // 2. Call doo_player_ajax
        const postData = `action=doo_player_ajax&post=${p}&nume=${n}&type=${ty}&nonce=${nonce}`;
        const ajaxRes = await this.httpClient.post(`${this.siteUrl}/wp-admin/admin-ajax.php`, postData, {
          headers: {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            Referer: pageUrl,
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        if (!ajaxRes.html || !ajaxRes.html.startsWith("{")) {
          return res.status(502).send("Ajax player failed");
        }

        const ajaxData = JSON.parse(ajaxRes.html);
        if (!ajaxData.embed_url) {
          return res.status(502).send("No embed URL in player data");
        }

        let embedUrl = ajaxData.embed_url;
        if (embedUrl.startsWith("//")) embedUrl = "https:" + embedUrl;

        // 3. Fetch embed player HTML to get real-time streamToken
        const embedRes = await this.httpClient.get(embedUrl, {
          headers: { Referer: pageUrl },
        });

        const embedHtml = embedRes.html;
        const tokenMatch = embedHtml.match(/streamToken\s*=\s*["\x27]([^"\x27]+)["\x27]/);
        const streamToken = tokenMatch ? tokenMatch[1] : "";

        const paths = (embedHtml.match(/(?:\\\/|\/)(m3u8|playlist)(?:\\\/|\/)[^"\x27]+/g) || [])
          .map((x) => x.replace(/\\\//g, "/"));

        const m3u8Path = paths.find((x) => x.includes("/m3u8/")) || paths[0];
        if (!m3u8Path) {
          return res.status(502).send("No HLS paths in player embed");
        }

        const masterUrl = new URL(m3u8Path, embedUrl).href;

        // 4. Fetch the master playlist with fresh token
        const upstream = await this.httpClient.get(masterUrl, {
          headers: { Referer: embedUrl, "X-Stream-Token": streamToken },
        });

        const rawText = (upstream.html || "").trimStart();
        if (upstream.status !== 200 || !rawText.startsWith("#EXTM3U")) {
          console.warn(`[HlsProxy] On-demand upstream non-playlist: status=${upstream.status}, text=${rawText.slice(0, 80)}`);
          return res.status(502).send("Upstream returned non-playlist");
        }

        // 5. Rewrite rendition sub-playlists
        const lines = rawText.split("\n");
        const rewritten = [];
        const cleanBase = (serverBase || "").replace(/\/+$/, "");

        for (let i = 0; i < lines.length; i++) {
          const line = lines[i].trim();
          if (!line) {
            rewritten.push("");
            continue;
          }

          if (line.startsWith("#")) {
            rewritten.push(line);
            continue;
          }

          const absoluteRenditionUrl = new URL(line, masterUrl).href;
          const subTarget = Buffer.from(absoluteRenditionUrl).toString("base64url");
          const subToken = Buffer.from(streamToken).toString("base64url");
          const subRef = Buffer.from(embedUrl).toString("base64url");
          const subSig = this.sign(`${absoluteRenditionUrl}:${streamToken}`);

          rewritten.push(`${cleanBase}/proxy/hls/playlist.m3u8?t=${subTarget}&k=${subToken}&r=${subRef}&s=${subSig}`);
        }

        res.setHeader("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8");
        res.setHeader("Cache-Control", "no-cache");
        return res.send(rewritten.join("\n"));
      } catch (err) {
        console.error("[HlsProxy] On-demand master playlist error:", err.message);
        return res.status(502).send("Upstream resolution error");
      }
    }

    // ── MODE B: STATIC TOKEN PROXY ──
    if (!t) return res.status(400).send("Missing target");

    let targetUrl;
    let streamToken = "";
    let embedUrl = "";
    try {
      targetUrl = Buffer.from(t, "base64url").toString("utf8");
      streamToken = k ? Buffer.from(k, "base64url").toString("utf8") : "";
      embedUrl = r ? Buffer.from(r, "base64url").toString("utf8") : "";
    } catch {
      return res.status(400).send("Invalid target encoding");
    }

    if (!this.verify(`${targetUrl}:${streamToken}`, s)) {
      return res.status(403).send("Invalid signature");
    }

    try {
      const headers = {};
      if (embedUrl) headers["Referer"] = embedUrl;
      if (streamToken) headers["X-Stream-Token"] = streamToken;

      const upstream = await this.httpClient.get(targetUrl, { headers });
      const rawText = (upstream.html || "").trimStart();
      if (upstream.status !== 200 || !rawText.startsWith("#EXTM3U")) {
        console.warn(`[HlsProxy] Upstream non-playlist: status=${upstream.status}, preview=${rawText.slice(0, 100)}`);
        return res.status(502).send("Upstream returned non-playlist");
      }

      const lines = rawText.split("\n");
      const rewritten = [];
      const cleanBase = (serverBase || "").replace(/\/+$/, "");

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) {
          rewritten.push("");
          continue;
        }

        if (line.startsWith("#")) {
          rewritten.push(line);
          continue;
        }

        const absoluteRenditionUrl = new URL(line, targetUrl).href;
        const subTarget = Buffer.from(absoluteRenditionUrl).toString("base64url");
        const subToken = Buffer.from(streamToken).toString("base64url");
        const subRef = Buffer.from(embedUrl).toString("base64url");
        const subSig = this.sign(`${absoluteRenditionUrl}:${streamToken}`);

        rewritten.push(`${cleanBase}/proxy/hls/playlist.m3u8?t=${subTarget}&k=${subToken}&r=${subRef}&s=${subSig}`);
      }

      res.setHeader("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8");
      res.setHeader("Cache-Control", "no-cache");
      return res.send(rewritten.join("\n"));
    } catch (err) {
      console.error("[HlsProxy] Master playlist error:", err.message);
      return res.status(502).send("Upstream error");
    }
  }

  async handleSubPlaylist(req, res, serverBase) {
    const { t, k, r, s } = req.query;
    if (!t) return res.status(400).send("Missing target");

    let targetUrl;
    let streamToken = "";
    let embedUrl = "";
    try {
      targetUrl = Buffer.from(t, "base64url").toString("utf8");
      streamToken = k ? Buffer.from(k, "base64url").toString("utf8") : "";
      embedUrl = r ? Buffer.from(r, "base64url").toString("utf8") : "";
    } catch {
      return res.status(400).send("Invalid target encoding");
    }

    if (!this.verify(`${targetUrl}:${streamToken}`, s)) {
      return res.status(403).send("Invalid signature");
    }

    try {
      const headers = {};
      if (embedUrl) headers["Referer"] = embedUrl;
      if (streamToken) headers["X-Stream-Token"] = streamToken;

      const upstream = await this.httpClient.get(targetUrl, { headers });
      const rawText = (upstream.html || "").trimStart();
      if (upstream.status !== 200 || !rawText.startsWith("#EXTM3U")) {
        console.warn(`[HlsProxy] Sub-playlist upstream non-playlist: status=${upstream.status}, preview=${rawText.slice(0, 100)}`);
        return res.status(502).send("Upstream returned non-playlist");
      }

      const lines = rawText.split("\n");
      const rewritten = [];

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) {
          rewritten.push(line);
          continue;
        }

        // Direct open CDN URLs work without any tokens
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
          rewritten.push(trimmed);
        } else {
          const absoluteChunkUrl = new URL(trimmed, targetUrl).href;
          rewritten.push(absoluteChunkUrl);
        }
      }

      res.setHeader("Content-Type", "application/vnd.apple.mpegurl; charset=utf-8");
      res.setHeader("Cache-Control", "no-cache");
      return res.send(rewritten.join("\n"));
    } catch (err) {
      console.error("[HlsProxy] Sub-playlist error:", err.message);
      return res.status(502).send("Upstream error");
    }
  }
}

module.exports = { HlsProxy };
