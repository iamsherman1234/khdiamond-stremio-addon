"use strict";

const crypto = require("crypto");

class HlsProxy {
  constructor(options = {}) {
    this.secret = (options.secret || process.env.PROXY_SECRET || "khdiamond_secret_2026").trim();
    this.httpClient = options.httpClient;
  }

  sign(data) {
    return crypto.createHmac("sha256", this.secret).update(String(data)).digest("hex").slice(0, 16);
  }

  verify(data, signature) {
    if (!signature || typeof signature !== "string") return false;
    const expected = this.sign(data);
    return signature.length === expected.length && crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
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
        console.warn(`[HlsProxy] Upstream non-playlist: status=${upstream.status}, preview=${rawText.slice(0, 100)}`);
        return res.status(502).send("Upstream returned non-playlist");
      }

      // Rewrite rendition URLs
      const lines = rawText.split("\n");
      const rewritten = [];

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

        // Rendition URL line
        const absoluteRenditionUrl = new URL(line, targetUrl).href;
        const subTarget = Buffer.from(absoluteRenditionUrl).toString("base64url");
        const subToken = Buffer.from(streamToken).toString("base64url");
        const subRef = Buffer.from(embedUrl).toString("base64url");
        const subSig = this.sign(`${absoluteRenditionUrl}:${streamToken}`);

        const cleanBase = (serverBase || "").replace(/\/+$/, "");
        rewritten.push(`${cleanBase}/proxy/hls/playlist.m3u8?t=${subTarget}&k=${subToken}&r=${subRef}&s=${subSig}`);
      }

      res.setHeader("Content-Type", "application/vnd.apple.mpegurl");
      res.setHeader("Cache-Control", "max-age=3600, public");
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

      // If chunks are relative, make them absolute or proxy them
      const lines = rawText.split("\n");
      const rewritten = [];

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) {
          rewritten.push(line);
          continue;
        }

        // Direct CDN URLs on khdmcloud.online work directly for all clients!
        if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
          rewritten.push(trimmed);
        } else {
          // Resolve relative segment
          const absoluteChunkUrl = new URL(trimmed, targetUrl).href;
          rewritten.push(absoluteChunkUrl);
        }
      }

      res.setHeader("Content-Type", "application/vnd.apple.mpegurl");
      res.setHeader("Cache-Control", "max-age=3600, public");
      return res.send(rewritten.join("\n"));
    } catch (err) {
      console.error("[HlsProxy] Sub-playlist error:", err.message);
      return res.status(502).send("Upstream error");
    }
  }
}

module.exports = { HlsProxy };
