"use strict";

const cheerio = require("cheerio");
const { SimpleCache } = require("./cache");
const { resolveMetadata, parseStreamId } = require("./cinemeta");

const SEARCH_NONCE = "d7f551d414";

class KhdiamondScraper {
  constructor(httpClient, hlsProxy, options = {}) {
    this.client = httpClient;
    this.hlsProxy = hlsProxy;
    const opts = typeof options === "string" ? { userToken: options } : (options || {});
    this.userToken = opts.userToken || "";
    this.siteUrl = (opts.siteUrl || process.env.SITE_URL || "https://khdiamond.net").replace(/\/+$/, "");
    this.cache = new SimpleCache(parseInt(opts.cacheTtl || process.env.CACHE_TTL_S || "3600", 10));
  }

  _normalizePath(rawPath) {
    if (!rawPath) return "/";
    let p = rawPath.replace(this.siteUrl, "");
    p = "/" + p.replace(/^\/+|\/+$/g, "") + "/";
    return p;
  }

  _pathToId(path) {
    const cleanPath = this._normalizePath(path);
    return `khd:${Buffer.from(cleanPath).toString("base64url")}`;
  }

  _idToPath(id) {
    if (!id || !id.startsWith("khd:")) return id;
    const raw = id.slice(4).split(":")[0];
    try {
      const decoded = Buffer.from(raw, "base64url").toString("utf8");
      return this._normalizePath(decoded);
    } catch {
      return this._normalizePath(raw);
    }
  }

  _cleanTitle(title) {
    return String(title || "")
      .replace(/[:\-–—()]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  _similarity(s1, s2) {
    if (!s1 || !s2) return 0;
    const a = s1.toLowerCase().trim();
    const b = s2.toLowerCase().trim();
    if (a === b) return 1.0;
    if (a.includes(b) || b.includes(a)) return 0.8;
    const wordsA = a.split(/\s+/);
    const wordsB = b.split(/\s+/);
    const common = wordsA.filter((w) => wordsB.includes(w));
    return (2.0 * common.length) / (wordsA.length + wordsB.length);
  }

  async searchMedia(query) {
    const cleanQ = this._cleanTitle(query);
    if (!cleanQ) return [];

    const cacheKey = `search_${cleanQ}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    const items = [];

    // 1. Try wp-json/dooplay/search
    try {
      const searchUrl = `${this.siteUrl}/wp-json/dooplay/search/?keyword=${encodeURIComponent(cleanQ)}&nonce=${SEARCH_NONCE}`;
      const res = await this.client.get(searchUrl, { timeout: 6000 });
      if (res.status === 200 && res.html) {
        const data = JSON.parse(res.html);
        if (data && typeof data === "object" && !data.error) {
          for (const [id, item] of Object.entries(data)) {
            if (!item || !item.url) continue;
            items.push({
              id,
              title: item.title,
              url: item.url,
              poster: item.img,
              year: item.extra?.date ? parseInt(item.extra.date, 10) : null,
            });
          }
        }
      }
    } catch (_) {}

    // 2. Fallback to HTML search page if wp-json was empty
    if (items.length === 0) {
      try {
        const htmlUrl = `${this.siteUrl}/page/1/?s=${encodeURIComponent(cleanQ)}`;
        const res = await this.client.get(htmlUrl, { timeout: 8000 });
        if (res.status === 200 && res.html) {
          const $ = cheerio.load(res.html);
          $("article.item, .search-page .result-item, .item.movies, .item.tvshows").each((_, el) => {
            const card = $(el);
            const link = card.find("a[href]").first();
            const href = link.attr("href");
            if (!href || href.includes("/category/")) return;

            const title =
              card.find(".title, h2, h3").first().text().trim() ||
              link.attr("title") ||
              "";
            const poster =
              card.find("img").attr("data-src") ||
              card.find("img").attr("src") ||
              "";
            const yearMatch = card.text().match(/\b(19\d\d|20\d\d)\b/);
            const year = yearMatch ? parseInt(yearMatch[1], 10) : null;

            if (href && title) {
              items.push({
                id: this._pathToId(href),
                title,
                url: href,
                poster,
                year,
              });
            }
          });
        }
      } catch (_) {}
    }

    this.cache.set(cacheKey, items, 1800);
    return items;
  }

  async getCatalog(type, catalogId = "", { search = "", skip = 0 } = {}) {
    // ── UNLOCKED / PURCHASED LIBRARY ──
    if (catalogId === "khd_unlocked") {
      const userKey = this.userToken || (this.client && this.client.user) || "default";
      const cacheKey = `cat_unlocked_${userKey}_${skip}`;
      const cached = this.cache.get(cacheKey);
      if (cached) return cached;

      try {
        const res = await this.client.get(`${this.siteUrl}/my-account/`);
        const $ = cheerio.load(res.html);
        const metas = [];

        $("#items_movies article").each((_, el) => {
          const a = $(el).find(".data h3 a, a").first();
          const title = $(el).find(".data h3").text().trim() || a.text().trim();
          const href = a.attr("href");
          const poster = $(el).find("img").attr("src") || "";
          const year = $(el).find(".data span").text().trim() || undefined;

          if (href && title && !title.includes("ទស្សនា")) {
            metas.push({
              id: this._pathToId(href),
              type: href.includes("/tvshows/") ? "series" : "movie",
              name: title,
              poster: poster.startsWith("//") ? `https:${poster}` : poster,
              year,
            });
          }
        });

        const paged = metas.slice(skip, skip + 50);
        this.cache.set(cacheKey, paged, 1800);
        return paged;
      } catch (err) {
        console.error("[Scraper] Failed to fetch unlocked catalog:", err.message);
        return [];
      }
    }

    if (catalogId === "khboxmax_free" || catalogId === "free_movies") {
      const freeMovies = await this.fetchKhboxmaxFreeMovies();
      let filtered = freeMovies;
      if (search) {
        const query = search.toLowerCase();
        filtered = filtered.filter((m) => (m.title || "").toLowerCase().includes(query));
      }
      return filtered.slice(skip, skip + 50).map((m) => ({
        id: m.khd_id,
        type: "movie",
        name: m.title,
        poster: m.poster,
        year: m.year,
        description: m.description,
      }));
    }

    const pageNum = Math.floor(skip / 24) + 1;
    const cacheKey = `cat_${type}_${catalogId}_${search}_${pageNum}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    let targetUrl;
    if (search) {
      targetUrl = `${this.siteUrl}/page/${pageNum}/?s=${encodeURIComponent(search)}`;
    } else if (type === "series") {
      targetUrl = `${this.siteUrl}/tvshows/page/${pageNum}/`;
    } else {
      targetUrl = `${this.siteUrl}/movies/page/${pageNum}/`;
    }

    let html;
    try {
      const res = await this.client.get(targetUrl);
      html = res.html;
    } catch (err) {
      // Fallback to base page if /page/1/ 404s
      if (pageNum === 1 && !search) {
        const fallbackUrl = type === "series" ? `${this.siteUrl}/tvshows/` : `${this.siteUrl}/movies/`;
        const res = await this.client.get(fallbackUrl);
        html = res.html;
      } else {
        console.error(`[Scraper] Failed to fetch catalog ${targetUrl}:`, err.message);
        return [];
      }
    }

    const $ = cheerio.load(html);
    const metas = [];

    const cardSelectors = [
      "article.item",
      "article.post",
      ".TPost",
      ".movie-item",
      ".item.movies",
      ".item.tvshows",
      "div.post",
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

      if (!metas.some((m) => m.id === id)) {
        metas.push({
          id,
          type: type || (href.includes("/tvshows/") ? "series" : "movie"),
          name: title,
          poster: poster.startsWith("//") ? `https:${poster}` : poster,
          year,
          description: card.find(".texto, .synopsis, p").text().trim() || undefined,
        });
      }
    });

    this.cache.set(cacheKey, metas, 1800);
    return metas;
  }

  async getSyncCatalog(hostBase, { includeSeriesEpisodes = true, includeFree = false } = {}) {
    const userKey = this.userToken || (this.client && this.client.user) || "default";
    const cacheKey = `sync_cat_${userKey}_${includeSeriesEpisodes}_${includeFree}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    try {
      // 1. Fetch initial account page (Page 0)
      const pageRes = await this.client.get(`${this.siteUrl}/my-account/`);
      const $ = cheerio.load(pageRes.html);

      const userMatch = pageRes.html.match(/data-user="(\d+)"/);
      const userId = userMatch ? userMatch[1] : (this.client && this.client.userId) || "20286";

      const rawArticles = [];
      const parsePageArticles = (html) => {
        const $c = cheerio.load(html);
        $c("article.simple, #items_movies article, #items_tvshows article, article").each((_, el) => {
          const rawId = $c(el).attr("id") || "";
          const movieId = rawId.replace(/^[pv]/, "").trim();
          const a = $c(el).find(".data h3 a, a").first();
          const title = $c(el).find(".data h3").text().trim() || a.text().trim();
          const href = a.attr("href") || "";
          const poster = $c(el).find("img").attr("src") || "";
          const year = $c(el).find(".data span").text().trim() || "";

          if (!href || !title || title.includes("ទស្សនា")) return;
          const finalId = movieId || (href.match(/\/(\d+)\/?$/) ? href.match(/\/(\d+)\/?$/)[1] : "");
          if (!finalId) return;

          const isSeries = href.includes("/tvshows/") || $c(el).hasClass("tvshows");

          rawArticles.push({
            id: finalId,
            title,
            href,
            poster: poster.startsWith("//") ? `https:${poster}` : poster,
            year,
            isSeries,
          });
        });
      };

      parsePageArticles(pageRes.html);

      // 2. Loop through AJAX pages until all are fetched
      for (let page = 1; page <= 20; page++) {
        const postData = `action=next_page_list&page=${page}&typepost=_dt_list_users&user=${userId}&template=purchased_movies`;
        try {
          const ajaxRes = await this.client.post(`${this.siteUrl}/wp-admin/admin-ajax.php`, postData, {
            headers: {
              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
              Referer: `${this.siteUrl}/my-account/`,
              "X-Requested-With": "XMLHttpRequest",
            },
          });

          if (!ajaxRes.html || ajaxRes.html.includes("no_fav") || !ajaxRes.html.includes("article")) {
            break;
          }
          parsePageArticles(ajaxRes.html);
        } catch (ajaxErr) {
          console.warn(`[Scraper] AJAX catalog page ${page} error:`, ajaxErr.message);
          break;
        }
      }

      // 3. Deduplicate
      const seenIds = new Set();
      const movies = [];
      const seriesList = [];

      for (const a of rawArticles) {
        if (!a.id || seenIds.has(a.id)) continue;
        seenIds.add(a.id);

        const isFree = a.title.includes("ឥតគិតថ្លៃ");
        if (isFree && !includeFree) continue;

        if (a.isSeries) {
          seriesList.push(a);
        } else {
          movies.push(a);
        }
      }

      const items = [];

      // 4. Add Movies
      for (const m of movies) {
        const path = this._normalizePath(m.href.replace(/^https?:\/\/[^/]+/, ""));
        const slug = path.replace(/^\/(?:movies|tvshows)\//, "").replace(/\/+$/, "");
        const khdId = this._pathToId(m.href);

        const streamUrl1080 = this.hlsProxy.buildOnDemandStreamUrl(hostBase, m.href, m.id, 1, "movie", this.userToken);
        const streamUrl4k = this.hlsProxy.buildOnDemandStreamUrl(hostBase, m.href, m.id, 2, "movie", this.userToken);

        const candidates = [
          ["KhDiamond Direct CDN (1080p)", streamUrl1080],
          ["KhDiamond Direct CDN (4K)", streamUrl4k],
        ];

        items.push({
          movie_id: m.id,
          movie_id_4k: m.id,
          title: m.title,
          title_khmer: m.title,
          title_english: m.title,
          year: m.year || "",
          type: "movie",
          slug,
          khd_id: khdId,
          href: m.href,
          poster: m.poster,
          stream_url: streamUrl1080,
          stream_url_4k: streamUrl4k,
          candidates,
        });
      }

      // 5. Expand Series & Episodes
      for (const s of seriesList) {
        const sPath = this._normalizePath(s.href.replace(/^https?:\/\/[^/]+/, ""));
        const sSlug = sPath.replace(/^\/(?:movies|tvshows)\//, "").replace(/\/+$/, "");
        const sKhdId = this._pathToId(s.href);

        if (!includeSeriesEpisodes) {
          const sUrl = this.hlsProxy.buildOnDemandStreamUrl(hostBase, s.href, s.id, 1, "tv", this.userToken);
          items.push({
            movie_id: s.id,
            movie_id_4k: s.id,
            title: s.title,
            title_khmer: s.title,
            title_english: s.title,
            year: s.year || "",
            type: "series",
            slug: sSlug,
            khd_id: sKhdId,
            href: s.href,
            poster: s.poster,
            stream_url: sUrl,
            candidates: [["KhDiamond Master Stream", sUrl]],
          });
          continue;
        }

        try {
          const sRes = await this.client.get(s.href);
          const $s = cheerio.load(sRes.html);
          const episodes = [];

          $s("a[href*=\"/episodes/\"], .video-card").each((_, el) => {
            const a = $(el).is("a") ? $(el) : $(el).find("a[href*=\"/episodes/\"]").first();
            const href = a.attr("href");
            if (href && !episodes.some((e) => e.href === href)) {
              const card = a.closest(".video-card");
              const metaText = card.find(".meta").text().trim();
              const sMatch = metaText.match(/S(\d+)\s*-\s*E(\d+)/i);
              const season = sMatch ? parseInt(sMatch[1], 10) : 1;
              const epNum = sMatch ? parseInt(sMatch[2], 10) : episodes.length + 1;
              const epPoster = card.find("img").attr("src") || s.poster;

              episodes.push({
                href,
                season,
                episode: epNum,
                poster: epPoster,
              });
            }
          });

          if (episodes.length === 0) {
            episodes.push({ href: s.href, season: 1, episode: 1, poster: s.poster });
          }

          for (const ep of episodes) {
            const epPath = this._normalizePath(ep.href.replace(/^https?:\/\/[^/]+/, ""));
            const epKhdId = `${sKhdId}:1:${ep.episode}:${Buffer.from(epPath).toString("base64url")}`;
            const epStreamUrl = this.hlsProxy.buildOnDemandStreamUrl(hostBase, ep.href, s.id, 1, "tv", this.userToken);
            const epStreamUrl4k = this.hlsProxy.buildOnDemandStreamUrl(hostBase, ep.href, s.id, 2, "tv", this.userToken);

            const candidates = [
              ["KhDiamond Direct CDN (1080p)", epStreamUrl],
              ["KhDiamond Direct CDN (4K)", epStreamUrl4k],
            ];

            items.push({
              movie_id: s.id,
              movie_id_4k: s.id,
              title: s.title,
              title_khmer: s.title,
              title_english: s.title,
              series_title: s.title,
              year: s.year || "",
              type: "series",
              season: ep.season,
              episode: ep.episode,
              slug: `${sSlug}-s${ep.season}e${ep.episode}`,
              khd_id: epKhdId,
              href: ep.href,
              poster: ep.poster,
              stream_url: epStreamUrl,
              stream_url_4k: epStreamUrl4k,
              candidates,
            });
          }
        } catch (sErr) {
          console.warn(`[Scraper] Could not expand series episodes for ${s.title}:`, sErr.message);
        }
      }

      // 6. Include KhBoxMax Free Movies if requested
      if (includeFree) {
        const freeItems = await this.fetchKhboxmaxFreeMovies();
        items.push(...freeItems);
      }

      console.log(`[Scraper] getSyncCatalog: built ${items.length} total items (${movies.length} movies, ${items.length - movies.length} series/free)`);
      this.cache.set(cacheKey, items, 1800);
      return items;
    } catch (err) {
      console.error("[Scraper] Failed to fetch sync catalog:", err.message);
      return [];
    }
  }

  async fetchKhboxmaxFreeMovies() {
    const cacheKey = "khboxmax_free_movies_catalog";
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    try {
      const res = await this.client.get("https://khboxmax.net/api/movies.php");
      if (!res.html || !res.html.startsWith("[")) {
        return [];
      }
      const allMovies = JSON.parse(res.html);
      const freeMovies = allMovies.filter((m) => {
        const isFreeAccess = (m.access_control || "").toLowerCase() === "free";
        const hasFreeGenre = (m.genre || "").toLowerCase().includes("free");
        return isFreeAccess || hasFreeGenre;
      });

      const freeItems = [];
      for (const m of freeMovies) {
        const eps = Array.isArray(m.episodes) ? m.episodes : [];
        const primaryUrl = eps.length > 0 ? eps[0].url : "";
        if (!primaryUrl) continue;

        const candidates = eps.map((ep) => [
          `KhBoxMax ${(ep.title || "Direct").trim()}`,
          ep.url,
        ]);

        const year = (m.releaseDate || "").slice(0, 4);

        freeItems.push({
          movie_id: `khbox_${m.id}`,
          movie_id_4k: `khbox_${m.id}`,
          title: m.title,
          title_khmer: m.title,
          title_english: m.title,
          year: year,
          type: "movie",
          slug: `khbox-${m.slug || m.id}`,
          khd_id: `khbox:${m.id}`,
          href: `https://khboxmax.net/movies/${m.slug || m.id}`,
          poster: m.poster || "",
          stream_url: primaryUrl,
          stream_url_4k: primaryUrl,
          candidates,
          source: "khboxmax",
          is_free: true,
          description: m.description || "",
        });
      }

      console.log(`[Scraper] Loaded ${freeItems.length} free movies from KhBoxMax`);
      this.cache.set(cacheKey, freeItems, 3600);
      return freeItems;
    } catch (err) {
      console.error("[Scraper] Failed to fetch KhBoxMax free movies:", err.message);
      return [];
    }
  }

  async getMeta(type, id) {
    const cacheKey = `meta_${id}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    if (id.startsWith("khbox:") || id.startsWith("khbox_")) {
      const khboxId = id.replace(/^khbox[:_]/, "");
      const freeMovies = await this.fetchKhboxmaxFreeMovies();
      const movie = freeMovies.find((m) => m.movie_id === `khbox_${khboxId}` || m.khd_id === `khbox:${khboxId}`);
      if (movie) {
        const meta = {
          id: id,
          type: "movie",
          name: movie.title,
          poster: movie.poster,
          description: movie.description || `${movie.title} - Free Movie on KhBoxMax`,
          genres: ["Free", "Khmer Dubbed"],
          releaseInfo: movie.year,
        };
        this.cache.set(cacheKey, meta, 3600);
        return meta;
      }
    }

    const path = this._idToPath(id);
    const targetUrl = `${this.siteUrl}${path}`;

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

    const yearMatch =
      $("span.date, .year, .release").text().match(/\b(19\d\d|20\d\d)\b/) ||
      res.html.match(/\b(19\d\d|20\d\d)\b/);
    const year = yearMatch ? yearMatch[1] : undefined;

    const meta = {
      id,
      type: type || (path.includes("/tvshows/") ? "series" : "movie"),
      name: title,
      poster: poster.startsWith("//") ? `https:${poster}` : poster,
      background: background && background.startsWith("//") ? `https:${background}` : background,
      description,
      genres: genres.length > 0 ? genres : ["Khmer Dubbed"],
      releaseInfo: year,
    };

    // Parse TV series episodes
    if (meta.type === "series") {
      const videos = [];
      const episodeLinks = [];

      $("#seasons a[href*='/episodes/'], a[href*='/episodes/'], ul.episodios a").each((_, el) => {
        const href = $(el).attr("href");
        if (href && !episodeLinks.some((e) => e.href === href)) {
          const container = $(el).closest("li, div");
          const duration = container.find(".duration").text().trim();
          episodeLinks.push({ href, duration });
        }
      });

      if (episodeLinks.length > 0) {
        episodeLinks.forEach((item, index) => {
          const epNum = index + 1;
          const cleanEpPath = this._normalizePath(item.href);
          const epId = `${id}:1:${epNum}:${Buffer.from(cleanEpPath).toString("base64url")}`;

          videos.push({
            id: epId,
            title: `Episode ${epNum}${item.duration ? ` (${item.duration})` : ""}`,
            season: 1,
            episode: epNum,
            released: new Date().toISOString(),
          });
        });
      } else {
        // Fallback default episode
        videos.push({
          id: `${id}:1:1:${Buffer.from(path).toString("base64url")}`,
          title: "Full Series / Episode 1",
          season: 1,
          episode: 1,
        });
      }

      meta.videos = videos;
    }

    this.cache.set(cacheKey, meta, 7200);
    return meta;
  }

  async _extractTrailerFromModalOrEmbed(html, pageUrl, hostBase, mediaTitle) {
    const $ = cheerio.load(html);
    const trailers = [];

    // 1. Check modal or videobox iframes
    const iframeSrc = $("#modal-trailer iframe, .videobox iframe, .embed iframe, iframe.rptss, iframe[src*='khfullhd.co']").first().attr("src");
    if (iframeSrc) {
      const fullIframe = iframeSrc.startsWith("//") ? `https:${iframeSrc}` : iframeSrc;

      // Check stream.khfullhd.co or stream.khdiamond.net
      if (fullIframe.includes("khfullhd.co/e/") || fullIframe.includes("khdiamond.net/e/")) {
        try {
          const embRes = await this.client.get(fullIframe, { headers: { Referer: pageUrl } });
          const m3u8Match = embRes.html.match(/https?:\/\/[^\s"'<>]+\/hlsplaylist\/[^\s"'<>]+/i);
          if (m3u8Match) {
            const masterUrl = m3u8Match[0].replace(/\\/g, "");
            const proxyUrl = this.hlsProxy.buildProxyUrl(hostBase, masterUrl, "", fullIframe, this.userToken);
            trailers.push({
              name: "KHDiamond [Trailer 🇰🇭]",
              title: `${mediaTitle} • Khmer Trailer (ឈុតខ្លីៗ)\n🎬 Official 1080p Preview`,
              url: proxyUrl,
              type: "hls",
              behaviorHints: { notWebReady: false },
            });
          }
        } catch (_) {}
      }
      // Check YouTube trailer
      else if (fullIframe.includes("youtube.com") || fullIframe.includes("youtu.be")) {
        const ytMatch = fullIframe.match(/(?:embed\/|v=)([a-zA-Z0-9_-]{11})/);
        if (ytMatch) {
          trailers.push({
            name: "KHDiamond [Trailer 🇰🇭]",
            title: `${mediaTitle} • YouTube Trailer\n🎬 Official Preview`,
            ytId: ytMatch[1],
          });
        }
      }
    }

    return trailers;
  }

  async getStreams(type, id, hostBase) {
    const userKey = this.userToken || (this.client && this.client.user) || "default";
    const cacheKey = `streams_${userKey}_${type}_${id}`;
    const cached = this.cache.get(cacheKey);
    if (cached) return cached;

    if (id.startsWith("khbox:") || id.startsWith("khbox_")) {
      const khboxId = id.replace(/^khbox[:_]/, "");
      const freeMovies = await this.fetchKhboxmaxFreeMovies();
      const movie = freeMovies.find((m) => m.movie_id === `khbox_${khboxId}` || m.khd_id === `khbox:${khboxId}`);
      if (movie && movie.candidates) {
        const streams = movie.candidates.map(([name, url]) => ({
          name: "KhBoxMax [Free 🇰🇭]",
          title: `${movie.title} • ${name}\n🎬 Direct Free Stream`,
          url: url,
        }));
        this.cache.set(cacheKey, streams, 3600);
        return streams;
      }
      return [];
    }

    let targetUrl = null;
    let mediaTitle = "KhDiaMonD";
    let parentShowUrl = null;

    // ── CASE A: KHD ID (e.g. khd:bW92aWVzL... or khd:base:1:2:epPath) ──
    if (id.startsWith("khd:")) {
      const parts = id.split(":");
      if (parts.length >= 5) {
        // Series episode format: khd:<base64ShowPath>:<season>:<episode>:<base64EpPath>
        const showPath = Buffer.from(parts[1], "base64url").toString("utf8");
        const epPath = Buffer.from(parts[4], "base64url").toString("utf8");
        parentShowUrl = `${this.siteUrl}${this._normalizePath(showPath)}`;
        targetUrl = `${this.siteUrl}${this._normalizePath(epPath)}`;
      } else {
        // Movie or direct path
        targetUrl = `${this.siteUrl}${this._idToPath(id)}`;
      }
    }
    // ── CASE B: IMDB / TMDB ID (e.g. tt1234567 or tt1234567:1:1) ──
    else {
      const canonical = await resolveMetadata(type, id);
      if (!canonical || !canonical.title) {
        return [];
      }

      mediaTitle = canonical.title;
      const candidates = await this.searchMedia(canonical.title);
      if (!candidates.length) return [];

      let bestMatch = null;
      let bestScore = -1;

      for (const cand of candidates) {
        let score = this._similarity(canonical.title, cand.title);
        if (canonical.year && cand.year) {
          const diff = Math.abs(canonical.year - cand.year);
          if (diff === 0) score += 0.3;
          else if (diff === 1) score += 0.1;
          else score -= 0.3;
        }
        if (score > bestScore) {
          bestScore = score;
          bestMatch = cand;
        }
      }

      const match = bestMatch || candidates[0];
      if (!match || !match.url) return [];

      targetUrl = match.url;

      // For TV Series episode resolution:
      if (canonical.isSeries && canonical.episode) {
        parentShowUrl = match.url;
        const tvRes = await this.client.get(targetUrl);
        const $tv = cheerio.load(tvRes.html);
        const episodeLinks = [];
        $tv("#seasons a[href*='/episodes/'], a[href*='/episodes/']").each((_, el) => {
          const href = $(el).attr("href");
          if (href && !episodeLinks.includes(href)) episodeLinks.push(href);
        });

        const targetEpIndex = Math.max(0, canonical.episode - 1);
        if (episodeLinks.length > targetEpIndex) {
          targetUrl = episodeLinks[targetEpIndex];
        }
      }
    }

    if (!targetUrl) return [];

    console.log(`[Scraper] Extracting streams from: ${targetUrl}`);
    const streams = [];

    try {
      const pageRes = await this.client.get(targetUrl);
      const pageHtml = pageRes.html;
      const $ = cheerio.load(pageHtml);

      // Collect playable player options
      const fullOptions = [];
      const trailerOptions = [];

      $("#playeroptionsul li").each((_, el) => {
        const post = $(el).data("post");
        const nume = $(el).data("nume");
        const optType = $(el).data("type");
        const optText = $(el).text().trim();

        if (!post || !nume) return;

        const isTrailer = String(nume).toLowerCase() === "trailer" || optText.includes("ឈុតខ្លីៗ");
        if (isTrailer) {
          trailerOptions.push({ post, nume, type: optType || "movie", text: optText || "Trailer 🇰🇭" });
        } else {
          fullOptions.push({ post, nume, type: optType || "movie", text: optText });
        }
      });

      // 1. Generate full feature / episode streams first
      for (const opt of fullOptions.slice(0, 3)) {
        const label = opt.text || (opt.nume === 1 ? "1080p" : opt.nume === 2 ? "4K" : `Server ${opt.nume}`);
        const streamUrl = this.hlsProxy.buildOnDemandStreamUrl(hostBase, targetUrl, opt.post, opt.nume, opt.type, this.userToken);

        streams.push({
          name: `KHDiamond [${label}]`,
          title: `${mediaTitle} • Khmer Dubbed\n⚡ Full Video (${label})`,
          url: streamUrl,
          type: "hls",
          behaviorHints: {
            notWebReady: false,
          },
        });
      }

      // 2. Generate trailer streams (from player options e.g. Shang-Chi)
      for (const tOpt of trailerOptions) {
        const streamUrl = this.hlsProxy.buildOnDemandStreamUrl(hostBase, targetUrl, tOpt.post, tOpt.nume, tOpt.type, this.userToken);

        streams.push({
          name: `KHDiamond [Trailer 🇰🇭]`,
          title: `${mediaTitle} • Khmer Trailer (ឈុតខ្លីៗ)\n🎬 Official 1080p Preview`,
          url: streamUrl,
          type: "hls",
          behaviorHints: {
            notWebReady: false,
          },
        });
      }

      // 3. If no trailer stream yet, check modal/videobox trailer on current page
      const hasTrailer = streams.some((s) => s.name && s.name.includes("Trailer"));
      if (!hasTrailer) {
        const modalTrailers = await this._extractTrailerFromModalOrEmbed(pageHtml, targetUrl, hostBase, mediaTitle);
        streams.push(...modalTrailers);
      }

      // 4. For TV Series episodes with 0 streams, check parent TV show page for trailers (e.g. Doctor X)
      if (streams.length === 0 && (parentShowUrl || targetUrl.includes("/episodes/"))) {
        let showUrl = parentShowUrl;
        if (!showUrl) {
          showUrl = $("a[href*='/tvshows/']").filter((_, el) => {
            const h = $(el).attr("href") || "";
            return !h.endsWith("/tvshows/") && !h.endsWith("/tvshows");
          }).first().attr("href");
        }

        if (showUrl) {
          console.log(`[Scraper] Checking parent TV show for trailer: ${showUrl}`);
          const showRes = await this.client.get(showUrl);
          const showTrailers = await this._extractTrailerFromModalOrEmbed(showRes.html, showUrl, hostBase, mediaTitle);
          streams.push(...showTrailers);
        }
      }
    } catch (err) {
      console.error("[Scraper] Stream extraction failed:", err.message);
    }

    if (streams.length > 0) {
      this.cache.set(cacheKey, streams, 1800);
    }

    return streams;
  }
}

module.exports = { KhdiamondScraper };
