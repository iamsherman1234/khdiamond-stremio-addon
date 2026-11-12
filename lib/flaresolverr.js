"use strict";

const DEFAULT_TIMEOUT = 60000;

class FlareSolverrClient {
  constructor(options = {}) {
    this.endpoint = (options.endpoint || process.env.FLARESOLVERR_URL || "https://trawl.sudolocal.qzz.io/v1").replace(/\/+$/, "");
    this.timeout = parseInt(options.timeout || process.env.FLARESOLVERR_TIMEOUT || DEFAULT_TIMEOUT, 10);
    this.cookies = options.cookies || this._loadCookiesFromEnv();
    this.sessionId = null;
    this.cachedUserAgent = null;
  }

  _loadCookiesFromEnv() {
    try {
      if (process.env.COOKIES) {
        return JSON.parse(process.env.COOKIES);
      }
    } catch (e) {
      console.warn("[FlareSolverr] Failed to parse COOKIES from env:", e.message);
    }
    return [];
  }

  async sendCommand(payload) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout + 10000);

    try {
      const res = await fetch(this.endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`FlareSolverr HTTP ${res.status}: ${text}`);
      }

      const data = await res.json();
      return data;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async ensureSession() {
    if (this.sessionId) return this.sessionId;

    const requestedId = `khd_${Date.now()}`;
    try {
      const res = await this.sendCommand({
        cmd: "sessions.create",
        session: requestedId,
      });

      if (res && res.status === "ok") {
        this.sessionId = res.session || requestedId;
        console.log(`[FlareSolverr] Session created: ${this.sessionId}`);
        return this.sessionId;
      }
    } catch (err) {
      console.warn(`[FlareSolverr] Could not create explicit session (${err.message}). Falling back to stateless requests.`);
      this.sessionId = null;
    }
    return null;
  }

  async destroySession() {
    if (!this.sessionId) return;
    try {
      await this.sendCommand({
        cmd: "sessions.destroy",
        session: this.sessionId,
      });
      console.log(`[FlareSolverr] Destroyed session: ${this.sessionId}`);
    } catch (e) {
      // Ignore cleanup error
    }
    this.sessionId = null;
  }

  async get(url, { headers = {}, extraCookies = [] } = {}) {
    await this.ensureSession();

    const mergedCookies = [...this.cookies, ...extraCookies];
    const payload = {
      cmd: "request.get",
      url,
      maxTimeout: this.timeout,
    };

    if (this.sessionId) {
      payload.session = this.sessionId;
    }
    if (mergedCookies.length > 0) {
      payload.cookies = mergedCookies;
    }
    if (Object.keys(headers).length > 0) {
      payload.headers = headers;
    }

    let res;
    try {
      res = await this.sendCommand(payload);
    } catch (err) {
      // If session went stale, destroy and retry once
      if (this.sessionId && err.message.toLowerCase().includes("session")) {
        console.warn("[FlareSolverr] Session expired or invalid, retrying fresh session...");
        await this.destroySession();
        await this.ensureSession();
        if (this.sessionId) payload.session = this.sessionId;
        res = await this.sendCommand(payload);
      } else {
        throw err;
      }
    }

    if (!res || res.status !== "ok") {
      throw new Error(`FlareSolverr failed: ${res ? res.message : "Unknown error"}`);
    }

    const solution = res.solution || {};
    if (solution.userAgent) {
      this.cachedUserAgent = solution.userAgent;
    }

    return {
      status: solution.status || 200,
      url: solution.url || url,
      html: solution.response || "",
      headers: solution.headers || {},
      cookies: solution.cookies || [],
      userAgent: solution.userAgent || this.cachedUserAgent,
    };
  }

  async post(url, postData, { headers = {}, extraCookies = [] } = {}) {
    await this.ensureSession();

    const mergedCookies = [...this.cookies, ...extraCookies];
    const payload = {
      cmd: "request.post",
      url,
      postData,
      maxTimeout: this.timeout,
    };

    if (this.sessionId) {
      payload.session = this.sessionId;
    }
    if (mergedCookies.length > 0) {
      payload.cookies = mergedCookies;
    }
    if (Object.keys(headers).length > 0) {
      payload.headers = headers;
    }

    const res = await this.sendCommand(payload);
    if (!res || res.status !== "ok") {
      throw new Error(`FlareSolverr failed: ${res ? res.message : "Unknown error"}`);
    }

    const solution = res.solution || {};
    return {
      status: solution.status || 200,
      url: solution.url || url,
      html: solution.response || "",
      headers: solution.headers || {},
      cookies: solution.cookies || [],
      userAgent: solution.userAgent || this.cachedUserAgent,
    };
  }
}

module.exports = { FlareSolverrClient };
