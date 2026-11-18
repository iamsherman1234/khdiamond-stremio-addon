"use strict";

const nodeFetch = require("node-fetch");
const { SocksProxyAgent } = require("socks-proxy-agent");
const { FlareSolverrClient } = require("./flaresolverr");

const DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36";

let sharedClearance = {
  cookieStr: null,
  userAgent: null,
  cookies: [],
  expiresAt: 0,
  isFetching: null
};

let proxyDisabledUntil = 0;

async function getClearance(flaresolverr, siteUrl, forceRefresh = false) {
  if (!forceRefresh && sharedClearance.cookieStr && Date.now() < sharedClearance.expiresAt) {
    return sharedClearance;
  }
  if (sharedClearance.isFetching) {
    return await sharedClearance.isFetching;
  }

  sharedClearance.isFetching = (async () => {
    try {
      const solver = flaresolverr || new FlareSolverrClient();
      console.log(`[HttpClient] Acquiring fresh Cloudflare clearance for ${siteUrl}...`);
      const res = await solver.get(siteUrl);
      if (res && res.cookies && res.cookies.length > 0) {
        const cookieStr = res.cookies.map(c => `${c.name}=${c.value}`).join("; ");
        const userAgent = res.userAgent || DEFAULT_UA;
        sharedClearance.cookieStr = cookieStr;
        sharedClearance.userAgent = userAgent;
        sharedClearance.cookies = res.cookies;
        sharedClearance.expiresAt = Date.now() + 30 * 60 * 1000; // 30 minutes
        console.log(`[HttpClient] Cloudflare clearance acquired successfully (${res.cookies.length} cookies)`);
        return sharedClearance;
      }
    } catch (err) {
      console.warn(`[HttpClient] FlareSolverr clearance failed: ${err.message}`);
    } finally {
      sharedClearance.isFetching = null;
    }
    return null;
  })();

  return await sharedClearance.isFetching;
}

class HttpClient {
  constructor(options = {}) {
    this.siteUrl = (options.siteUrl || process.env.SITE_URL || "https://khdiamond.net").replace(/\/+$/, "");
    this.proxyUrl = options.proxyUrl !== undefined ? options.proxyUrl : (process.env.CAMBODIA_PROXY || "");
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
    if (this.proxyAgent && Date.now() > proxyDisabledUntil) {
      return this.proxyAgent;
    }
    return null;
  }

  _isProxyUsable() {
    return !!(this.proxyAgent && Date.now() > proxyDisabledUntil);
  }

  _markProxyFailed(err) {
    console.warn(`[HttpClient] Proxy disabled for 5 minutes due to error: ${err.message}`);
    proxyDisabledUntil = Date.now() + 5 * 60 * 1000;
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

        let res = null;

        // 1. Try via proxy if available and not marked failed
        if (this._isProxyUsable()) {
          try {
            res = await nodeFetch(`${this.siteUrl}/wp-admin/admin-ajax.php`, {
              method: "POST",
              headers: {
                "User-Agent": DEFAULT_UA,
                "Referer": `${this.siteUrl}/`,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
              },
              body: form.toString(),
              agent: this.proxyAgent,
              timeout: 6000
            });
            if (res.status === 403 || res.status === 503) {
              res = null; // Cloudflare blocked proxy
            }
          } catch (proxyErr) {
            this._markProxyFailed(proxyErr);
            res = null;
          }
        }

        // 2. If proxy failed or unavailable, use FlareSolverr clearance cookies directly
        if (!res) {
          const cl = await getClearance(this.flaresolverr, this.siteUrl);
          const clearanceCookies = cl ? cl.cookieStr : "";
          const ua = (cl && cl.userAgent) ? cl.userAgent : DEFAULT_UA;

          res = await nodeFetch(`${this.siteUrl}/wp-admin/admin-ajax.php`, {
            method: "POST",
            headers: {
              "User-Agent": ua,
              "Referer": `${this.siteUrl}/`,
              "X-Requested-With": "XMLHttpRequest",
              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
              ...(clearanceCookies ? { "Cookie": clearanceCookies } : {})
            },
            body: form.toString(),
            timeout: 10000
          });
        }

        if (!res || !res.ok) {
          console.warn(`[HttpClient] Login request failed: HTTP ${res ? res.status : 'no response'}`);
          return null;
        }

        const rawCookies = res.headers.raw()["set-cookie"] || [];
        if (!rawCookies.length) {
          console.warn("[HttpClient] Login succeeded but returned no cookies");
          return null;
        }

        const loginCookies = rawCookies.map(c => c.split(";")[0]).join("; ");
        const cl = sharedClearance && sharedClearance.cookieStr ? sharedClearance.cookieStr : "";
        const combined = cl ? `${loginCookies}; ${cl}` : loginCookies;

        this.cachedCookie = combined;
        this.cookieExpiresAt = Date.now() + 12 * 3600 * 1000;
        console.log(`[HttpClient] Successfully authenticated KHDiamond session for ${this.user}`);
        return combined;
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
    const cl = sharedClearance && sharedClearance.cookieStr ? sharedClearance : null;
    let ua = (cl && cl.userAgent) ? cl.userAgent : DEFAULT_UA;

    let cookieHeader = cookie || "";
    if (cl && cl.cookieStr) {
      if (!cookieHeader) {
        cookieHeader = cl.cookieStr;
      } else if (!cookieHeader.includes("cf_clearance")) {
        cookieHeader = `${cookieHeader}; ${cl.cookieStr}`;
      }
    }

    const reqHeaders = {
      "User-Agent": ua,
      "Referer": `${this.siteUrl}/`,
      ...headers
    };
    if (cookieHeader) {
      reqHeaders["Cookie"] = cookieHeader;
    }

    const agent = this.getAgent();

    try {
      const res = await nodeFetch(url, {
        method: "GET",
        headers: reqHeaders,
        agent,
        timeout
      });

      // If Cloudflare blocks with 403/503 challenge, refresh clearance and retry
      if (res.status === 403 || res.status === 503) {
        console.warn(`[HttpClient] HTTP ${res.status} on ${url}, refreshing clearance...`);
        const freshCl = await getClearance(this.flaresolverr, this.siteUrl, true);
        if (freshCl) {
          reqHeaders["User-Agent"] = freshCl.userAgent;
          const retryCookie = authenticated ? await this.getAuthCookie(true) : freshCl.cookieStr;
          reqHeaders["Cookie"] = retryCookie;
          const retryRes = await nodeFetch(url, {
            method: "GET",
            headers: reqHeaders,
            timeout
          });
          if (retryRes.ok) {
            const retryHtml = await retryRes.text();
            return { status: retryRes.status, url: retryRes.url || url, html: retryHtml, headers: retryRes.headers.raw() };
          }
        }
        return await this.flaresolverr.get(url, { headers: reqHeaders });
      }

      const html = await res.text();

      // Check if session expired and returned login page
      const isLoggedOut = authenticated && this.user && this.pass && (
        (html.includes("dooplay_login_user") && !html.includes("logged-in") && !url.includes("login")) ||
        (html.includes("<title>My Account") && html.includes("dooplay_login_user"))
      );
      if (isLoggedOut) {
        console.warn("[HttpClient] Session expired (login redirect detected). Refreshing cookie...");
        cookie = await this.getAuthCookie(true);
        if (cookie) {
          reqHeaders["Cookie"] = cookie;
          const retryRes = await nodeFetch(url, {
            method: "GET",
            headers: reqHeaders,
            agent: this.getAgent(),
            timeout
          });
          const retryHtml = await retryRes.text();
          return { status: retryRes.status, url: retryRes.url || url, html: retryHtml, headers: retryRes.headers.raw() };
        }
      }

      return {
        status: res.status,
        url: res.url || url,
        html,
        headers: res.headers.raw()
      };
    } catch (err) {
      if (agent) {
        this._markProxyFailed(err);
      }
      console.warn(`[HttpClient] Direct GET failed (${err.message}). Trying clearance/FlareSolverr...`);
      // Try direct nodeFetch without proxy using clearance
      try {
        const freshCl = await getClearance(this.flaresolverr, this.siteUrl);
        if (freshCl) {
          reqHeaders["User-Agent"] = freshCl.userAgent;
          reqHeaders["Cookie"] = cookie ? `${cookie}; ${freshCl.cookieStr}` : freshCl.cookieStr;
          const directRes = await nodeFetch(url, {
            method: "GET",
            headers: reqHeaders,
            timeout
          });
          if (directRes.ok) {
            const html = await directRes.text();
            return { status: directRes.status, url: directRes.url || url, html, headers: directRes.headers.raw() };
          }
        }
      } catch (directErr) {
        // Fall through to FlareSolverr
      }
      return await this.flaresolverr.get(url, { headers: reqHeaders });
    }
  }

  async post(url, body, { headers = {}, timeout = 12000, authenticated = true } = {}) {
    let cookie = authenticated ? await this.getAuthCookie() : null;
    const cl = sharedClearance && sharedClearance.cookieStr ? sharedClearance : null;
    const ua = (cl && cl.userAgent) ? cl.userAgent : DEFAULT_UA;

    let cookieHeader = cookie || "";
    if (cl && cl.cookieStr) {
      if (!cookieHeader) {
        cookieHeader = cl.cookieStr;
      } else if (!cookieHeader.includes("cf_clearance")) {
        cookieHeader = `${cookieHeader}; ${cl.cookieStr}`;
      }
    }

    const reqHeaders = {
      "User-Agent": ua,
      "Referer": `${this.siteUrl}/`,
      ...headers
    };
    if (cookieHeader) {
      reqHeaders["Cookie"] = cookieHeader;
    }

    const agent = this.getAgent();

    try {
      const res = await nodeFetch(url, {
        method: "POST",
        headers: reqHeaders,
        body,
        agent,
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
      if (agent) {
        this._markProxyFailed(err);
      }
      console.error(`[HttpClient] POST failed on ${url}:`, err.message);
      throw err;
    }
  }

  async fetchStream(url, { headers = {}, timeout = 15000 } = {}) {
    const cookie = await this.getAuthCookie();
    const cl = sharedClearance && sharedClearance.cookieStr ? sharedClearance : null;
    const ua = (cl && cl.userAgent) ? cl.userAgent : DEFAULT_UA;

    let cookieHeader = cookie || "";
    if (cl && cl.cookieStr) {
      if (!cookieHeader) {
        cookieHeader = cl.cookieStr;
      } else if (!cookieHeader.includes("cf_clearance")) {
        cookieHeader = `${cookieHeader}; ${cl.cookieStr}`;
      }
    }

    const reqHeaders = {
      "User-Agent": ua,
      "Referer": `${this.siteUrl}/`,
      ...headers
    };
    if (cookieHeader) {
      reqHeaders["Cookie"] = cookieHeader;
    }

    const agent = this.getAgent();

    try {
      return await nodeFetch(url, {
        method: "GET",
        headers: reqHeaders,
        agent,
        timeout
      });
    } catch (err) {
      if (agent) {
        this._markProxyFailed(err);
      }
      return await nodeFetch(url, {
        method: "GET",
        headers: reqHeaders,
        timeout
      });
    }
  }
}

module.exports = { HttpClient, DEFAULT_UA };
