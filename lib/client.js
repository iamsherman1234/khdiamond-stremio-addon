"use strict";

const nodeFetch = require("node-fetch");
const { SocksProxyAgent } = require("socks-proxy-agent");
const { FlareSolverrClient } = require("./flaresolverr");

const DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36";

class HttpClient {
  constructor(options = {}) {
    this.siteUrl = (options.siteUrl || process.env.SITE_URL || "https://khdiamond.net").replace(/\/+$/, "");
    this.proxyUrl = options.proxyUrl || process.env.CAMBODIA_PROXY || "socks5://100.108.63.53:1080";
    this.proxyAgent = this.proxyUrl ? new SocksProxyAgent(this.proxyUrl) : null;
    this.flaresolverr = options.flaresolverr || new FlareSolverrClient();
    this.user = options.user || process.env.KHDIAMOND_USER || "chumlayan95@gmail.com";
    this.pass = options.pass || process.env.KHDIAMOND_PASS || "240995L@yan";

    this.cachedCookie = options.cachedCookie || null;
    this.cookieExpiresAt = options.cookieExpiresAt || (options.cachedCookie ? Date.now() + 12 * 3600 * 1000 : 0);
    this.isAuthenticating = null;
  }

  async login(user, pass) {
    if (user) this.user = user;
    if (pass) this.pass = pass;
    this.cachedCookie = null;
    this.cookieExpiresAt = 0;
    const cookie = await this.getAuthCookie(true);
    if (!cookie) {
      throw new Error("Invalid KHDiamond credentials or login failed");
    }
    return cookie;
  }

  getAgent() {
    return this.proxyAgent;
  }

  async getAuthCookie(forceRefresh = false) {
    if (!forceRefresh && this.cachedCookie && Date.now() < this.cookieExpiresAt) {
      return this.cachedCookie;
    }

    if (this.isAuthenticating) {
      return this.isAuthenticating;
    }

    this.isAuthenticating = (async () => {
      try {
        const form = new URLSearchParams({
          action: "dooplay_login",
          log: this.user,
          pwd: this.pass,
          rmb: "forever",
          red: `${this.siteUrl}/`
        });

        const res = await nodeFetch(`${this.siteUrl}/wp-admin/admin-ajax.php`, {
          method: "POST",
          headers: {
            "User-Agent": DEFAULT_UA,
            "Referer": `${this.siteUrl}/`,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
          },
          body: form.toString(),
          agent: this.proxyAgent,
          timeout: 10000
        });

        if (!res.ok) {
          console.warn(`[HttpClient] Login request failed: HTTP ${res.status}`);
          return null;
        }

        const rawCookies = res.headers.raw()["set-cookie"] || [];
        if (!rawCookies.length) {
          console.warn("[HttpClient] Login succeeded but returned no cookies");
          return null;
        }

        const cookieStr = rawCookies.map(c => c.split(";")[0]).join("; ");
        this.cachedCookie = cookieStr;
        this.cookieExpiresAt = Date.now() + 12 * 3600 * 1000;
        console.log("[HttpClient] Successfully authenticated KHDiamond session");
        return cookieStr;
      } catch (err) {
        console.error(`[HttpClient] Auth error: ${err.message}`);
        return null;
      } finally {
        this.isAuthenticating = null;
      }
    })();

    return this.isAuthenticating;
  }

  async get(url, { headers = {}, timeout = 12000, authenticated = true } = {}) {
    let cookie = authenticated ? await this.getAuthCookie() : null;
    const reqHeaders = {
      "User-Agent": DEFAULT_UA,
      "Referer": `${this.siteUrl}/`,
      ...headers
    };
    if (cookie) {
      reqHeaders["Cookie"] = cookie;
    }

    try {
      const res = await nodeFetch(url, {
        method: "GET",
        headers: reqHeaders,
        agent: this.proxyAgent,
        timeout
      });

      // If Cloudflare blocks with 403/503 challenge, delegate to FlareSolverr
      if (res.status === 403 || res.status === 503) {
        console.warn(`[HttpClient] HTTP ${res.status} on ${url}, falling back to FlareSolverr...`);
        return await this.flaresolverr.get(url, { headers: reqHeaders });
      }

      const html = await res.text();

      // Check if session expired and returned login page
      if (authenticated && html.includes("<title>My Account") && html.includes("dooplay_login_user")) {
        console.warn("[HttpClient] Session expired (login redirect detected). Refreshing cookie...");
        cookie = await this.getAuthCookie(true);
        if (cookie) {
          reqHeaders["Cookie"] = cookie;
          const retryRes = await nodeFetch(url, {
            method: "GET",
            headers: reqHeaders,
            agent: this.proxyAgent,
            timeout
          });
          const retryHtml = await retryRes.text();
          return { status: retryRes.status, url: retryRes.url || url, html: retryHtml };
        }
      }

      return {
        status: res.status,
        url: res.url || url,
        html,
        headers: res.headers.raw()
      };
    } catch (err) {
      console.warn(`[HttpClient] Direct GET failed (${err.message}). Trying FlareSolverr...`);
      return await this.flaresolverr.get(url, { headers: reqHeaders });
    }
  }

  async post(url, body, { headers = {}, timeout = 12000, authenticated = true } = {}) {
    let cookie = authenticated ? await this.getAuthCookie() : null;
    const reqHeaders = {
      "User-Agent": DEFAULT_UA,
      "Referer": `${this.siteUrl}/`,
      ...headers
    };
    if (cookie) {
      reqHeaders["Cookie"] = cookie;
    }

    try {
      const res = await nodeFetch(url, {
        method: "POST",
        headers: reqHeaders,
        body,
        agent: this.proxyAgent,
        timeout
      });

      const text = await res.text();
      return {
        status: res.status,
        url: res.url || url,
        html: text,
        headers: res.headers.raw()
      };
    } catch (err) {
      console.error(`[HttpClient] POST failed on ${url}:`, err.message);
      throw err;
    }
  }

  async fetchStream(url, { headers = {}, timeout = 15000 } = {}) {
    const cookie = await this.getAuthCookie();
    const reqHeaders = {
      "User-Agent": DEFAULT_UA,
      "Referer": `${this.siteUrl}/`,
      ...headers
    };
    if (cookie && !reqHeaders["Cookie"]) {
      reqHeaders["Cookie"] = cookie;
    }

    return await nodeFetch(url, {
      method: "GET",
      headers: reqHeaders,
      agent: this.proxyAgent,
      timeout
    });
  }
}

module.exports = { HttpClient, DEFAULT_UA };
