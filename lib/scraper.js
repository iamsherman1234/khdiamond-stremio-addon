"use strict";

const cheerio = require("cheerio");
const { SimpleCache } = require("./cache");
const { extractStreamsFromHtml } = require("./extractors");

class KhdiamondScraper {
  constructor(flaresolverrClient, options = {}) {
    this.client = flaresolverrClient;
    this.siteUrl = (options.siteUrl || process.env.SITE_URL || "https://khdiamond.net").replace(/\/+$/, "");
    this.cache = new SimpleCache(parseInt(options.cacheTtl || process.env.CACHE_TTL_S || "3600", 10));
  }

  _pathToId(path) {
    const cleanPath = path.replace(this.siteUrl, "").replace(/^\/+|\/+$/g, "");
    return `khd:${Buffer.from(cleanPath).toString("base64url")}`;
  }

  _idToPath(id) {
    if (!id.startsWith("khd:")) return id;
    const raw = id.slice(4).split(":")[0];
    try {
      const decoded = Buffer.from(raw, "base64url").toString("utf8");
      return decoded.startsWith("/") ? decoded : `/${decoded}`;
    } catch {
      return `/${raw}`;
    }
  }

  async getCatalog(type, { search = "", skip = 0 } = {}) {
    const pageNum = Math.floor(skip / 20) + 1;
    const cacheKey = `cat_${type}_${search}_${pageNum}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    let targetUrl;
    if (search) {
      targetUrl = `${this.siteUrl}/page/${pageNum}/?s=${encodeURIComponent(search)}`;
    } else if (type === "series") {
      targetUrl = `${this.siteUrl}/series/page/${pageNum}/`;
    } else {
      targetUrl = `${this.siteUrl}/movies/page/${pageNum}/`;
    }

    console.log(`[Scraper] Fetching catalog: ${targetUrl}`);
    let html;
    try {
      const res = await this.client.get(targetUrl);
      html = res.html;
    } catch (err) {
      // Fallback to base page if /page/1/ 404s
      if (pageNum === 1 && !search) {
        const fallbackUrl = type === "series" ? `${this.siteUrl}/series/` : `${this.siteUrl}/movies/`;
        console.log(`[Scraper] Retrying fallback: ${fallbackUrl}`);
        const res = await this.client.get(fallbackUrl);
        html = res.html;
      } else {
        console.error(`[Scraper] Failed to fetch catalog ${targetUrl}:`, err.message);
        return [];
      }
    }

    const $ = cheerio.load(html);
    const metas = [];

    // Common card selectors across WordPress streaming themes (Dooplay, Toroflix, PsyPlay, etc.)
    const cardSelectors = [
      "article.item",
      "article.post",
      ".TPost",
      ".ml-item",
      ".movie-item",
      ".film-detail",
      ".item.movies",
      ".item.tvshows",
      "div.post",
      ".elementor-post"
    ].join(", ");

    $(cardSelectors).each((_, el) => {
      const card = $(el);
      const linkEl = card.find("a[href]").first();
      const href = linkEl.attr("href");
      if (!href || href === "#" || href.includes("/category/")) return;

      const title =
        card.find(".title, h2, h3, .entry-title").first().text().trim() ||
        linkEl.attr("title") ||
        card.find("img").first().attr("alt") ||
        "Untitled";

      const poster =
        card.find("img").attr("data-src") ||
        card.find("img").attr("data-lazy-src") ||
        card.find("img").attr("src") ||
        "";

      const yearMatch = card.text().match(/\b(19\d\d|20\d\d)\b/);
      const year = yearMatch ? yearMatch[1] : undefined;

      const id = this._pathToId(href);

      // Avoid duplicates
      if (!metas.some((m) => m.id === id)) {
        metas.push({
          id,
          type: type || (href.includes("/series/") || href.includes("/tvshows/") ? "series" : "movie"),
          name: title,
          poster: poster.startsWith("//") ? `https:${poster}` : poster,
          year,
          description: card.find(".texto, .synopsis, p").text().trim() || undefined,
        });
      }
    });

    // If cardSelectors found nothing, perform a generic scan of content links
    if (metas.length === 0) {
      $('main a[href], #content a[href], .site-content a[href]').each((_, el) => {
        const link = $(el);
        const href = link.attr("href") || "";
        const img = link.find("img");
        if (img.length > 0 && (href.includes("/movies/") || href.includes("/series/") || href.includes("/film/"))) {
          const title = link.attr("title") || img.attr("alt") || link.text().trim();
          const poster = img.attr("data-src") || img.attr("src") || "";
          const id = this._pathToId(href);
          if (title && !metas.some((m) => m.id === id)) {
            metas.push({
              id,
              type,
              name: title,
              poster,
            });
          }
        }
      });
    }

    this.cache.set(cacheKey, metas, 1800); // 30 min cache
    return metas;
  }

  async getMeta(type, id) {
    const cacheKey = `meta_${id}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    const path = this._idToPath(id);
    const targetUrl = `${this.siteUrl}${path}`;
    console.log(`[Scraper] Fetching meta details: ${targetUrl}`);

    const res = await this.client.get(targetUrl);
    const $ = cheerio.load(res.html);

    const title =
      $("h1.entry-title, h1.title, .data h1, h1").first().text().trim() ||
      $("meta[property='og:title']").attr("content") ||
      "Unknown Title";

    const poster =
      $(".poster img, .sheader .poster img, meta[property='og:image']").first().attr("src") ||
      $("meta[property='og:image']").attr("content") ||
      "";

    const background =
      $(".backdrop img, .sback, meta[property='og:image:secure_url']").first().attr("src") ||
      poster;

    const description =
      $(".wp-content p, .sinopsis, .entry-content p, #info .description, meta[property='og:description']")
        .first()
        .text()
        .trim() || "";

    const genres = [];
    $(".sgeneros a, .genres a, .entry-meta a[href*='/genre/']").each((_, el) => {
      genres.push($(el).text().trim());
    });

    const yearMatch = $("span.date, .year, .release").text().match(/\b(19\d\d|20\d\d)\b/) ||
      res.html.match(/\b(19\d\d|20\d\d)\b/);
    const year = yearMatch ? yearMatch[1] : undefined;

    const meta = {
      id,
      type,
      name: title,
      poster: poster.startsWith("//") ? `https:${poster}` : poster,
      background: background && background.startsWith("//") ? `https:${background}` : background,
      description,
      genres: genres.length > 0 ? genres : ["Khmer Dubbed"],
      releaseInfo: year,
    };

    // If series, parse episodes
    if (type === "series") {
      const videos = [];
      const episodeContainers = $("#seasons, ul.episodios, .episodes-list, .episodios li, .les-content a");

      if (episodeContainers.length > 0) {
        episodeContainers.find("li, a").each((i, el) => {
          const item = $(el);
          const link = item.is("a") ? item : item.find("a").first();
          const epUrl = link.attr("href");
          if (!epUrl) return;

          const text = item.text().trim();
          const epNumMatch = text.match(/(?:ep(?:isode)?|ភាគ)\s*(\d+)/i) || text.match(/\b(\d+)\b/);
          const seasonMatch = text.match(/(?:season|s)\s*(\d+)/i);

          const episodeNum = epNumMatch ? parseInt(epNumMatch[1], 10) : i + 1;
          const seasonNum = seasonMatch ? parseInt(seasonMatch[1], 10) : 1;

          videos.push({
            id: `${id}:${seasonNum}:${episodeNum}`,
            title: `Episode ${episodeNum}`,
            season: seasonNum,
            episode: episodeNum,
            released: new Date().toISOString(),
          });
        });
      }

      // If no nested episodes found, generate a single episode 1 default
      if (videos.length === 0) {
        videos.push({
          id: `${id}:1:1`,
          title: "Full Series / Episode 1",
          season: 1,
          episode: 1,
        });
      }

      meta.videos = videos;
    }

    this.cache.set(cacheKey, meta, 7200); // 2 hour cache
    return meta;
  }

  async getStreams(type, id) {
    const cacheKey = `streams_${id}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    // Handle series episode format: khd:slug:s:ep
    const parts = id.split(":");
    const baseId = `${parts[0]}:${parts[1]}`;
    const season = parts[2];
    const episode = parts[3];

    const path = this._idToPath(baseId);
    let targetUrl = `${this.siteUrl}${path}`;

    // If episode specific URL convention exists
    if (season && episode) {
      // Check if path already contains episode or try standard episode permalink
      if (!path.includes("-episode-") && !path.includes("/episode/")) {
        // e.g. /series/name-season-1-episode-2/
      }
    }

    console.log(`[Scraper] Extracting streams from: ${targetUrl}`);
    const res = await this.client.get(targetUrl);
    const html = res.html;
    const $ = cheerio.load(html);

    const streams = [];

    // 1. Direct stream extraction from page HTML (m3u8, mp4, pixeldrain)
    const directStreams = await extractStreamsFromHtml(html, targetUrl);
    streams.push(...directStreams);

    // 2. Scan iframes embedded in page
    const iframes = [];
    $("iframe[src]").each((_, el) => {
      const src = $(el).attr("src");
      if (src && !src.includes("challenges.cloudflare") && !src.includes("googletagmanager")) {
        iframes.push(src.startsWith("//") ? `https:${src}` : src);
      }
    });

    // 3. Scan Dooplay AJAX players if present
    const dooElements = $("[data-post][data-nume][data-type]");
    if (dooElements.length > 0) {
      for (let i = 0; i < dooElements.length; i++) {
        const el = $(dooElements[i]);
        const post = el.attr("data-post");
        const nume = el.attr("data-nume");
        const pType = el.attr("data-type");

        try {
          const ajaxUrl = `${this.siteUrl}/wp-admin/admin-ajax.php`;
          const postData = `action=doo_player_ajax&post=${post}&nume=${nume}&type=${pType}`;
          const ajaxRes = await this.client.post(ajaxUrl, postData, {
            headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
          });

          if (ajaxRes.html) {
            const innerStreams = await extractStreamsFromHtml(ajaxRes.html, targetUrl);
            streams.push(...innerStreams);

            const $inner = cheerio.load(ajaxRes.html);
            const innerIframe = $inner("iframe[src]").attr("src");
            if (innerIframe) {
              iframes.push(innerIframe.startsWith("//") ? `https:${innerIframe}` : innerIframe);
            }
          }
        } catch (e) {
          console.warn("[Scraper] Dooplay AJAX player error:", e.message);
        }
      }
    }

    // 4. Resolve iframes
    for (const iframeUrl of iframes) {
      try {
        console.log(`[Scraper] Inspecting player iframe: ${iframeUrl}`);
        const iframeRes = await this.client.get(iframeUrl, {
          headers: { Referer: targetUrl },
        });

        const iframeStreams = await extractStreamsFromHtml(iframeRes.html, iframeUrl);
        streams.push(...iframeStreams);
      } catch (err) {
        console.warn(`[Scraper] Could not resolve iframe ${iframeUrl}:`, err.message);
        // Fallback: supply external stream link
        streams.push({
          name: "KHDiamond [Web Player]",
          title: "External Web Player",
          externalUrl: iframeUrl,
        });
      }
    }

    // Deduplicate streams by URL
    const uniqueStreams = [];
    const seenUrls = new Set();
    for (const s of streams) {
      const u = s.url || s.externalUrl;
      if (u && !seenUrls.has(u)) {
        seenUrls.add(u);
        uniqueStreams.push(s);
      }
    }

    this.cache.set(cacheKey, uniqueStreams, 1800);
    return uniqueStreams;
  }
}

module.exports = { KhdiamondScraper };
