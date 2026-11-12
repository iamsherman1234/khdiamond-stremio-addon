"use strict";

const nodeFetch = require("node-fetch");
const { SimpleCache } = require("./cache");

const CINEMETA_BASE = process.env.CINEMETA_URL || "https://v3-cinemeta.strem.io";
const TMDB_API_KEYS = [
  "7c017d58f5410957aae99e499521e95b",
  "307b7b8ef035c6aa336900aef4e203bd",
  "439c478a771f35c05022f9feabcca01c"
];

let keyIdx = 0;
function getTmdbKey() {
  const k = TMDB_API_KEYS[keyIdx % TMDB_API_KEYS.length];
  keyIdx++;
  return k;
}

const metaCache = new SimpleCache(86400); // 24 hours

function parseStreamId(rawId) {
  const parts = String(rawId || "").split(":");
  const prefix = parts[0];
  let imdbId = null;
  let tmdbId = null;
  let season = null;
  let episode = null;

  if (prefix.startsWith("tt")) {
    imdbId = prefix;
    if (parts.length >= 3) {
      season = parseInt(parts[1], 10) || null;
      episode = parseInt(parts[2], 10) || null;
    }
  } else if (prefix === "tmdb" && parts.length >= 2) {
    tmdbId = parseInt(parts[1], 10) || null;
    if (parts.length >= 4) {
      season = parseInt(parts[2], 10) || null;
      episode = parseInt(parts[3], 10) || null;
    }
  }

  return { imdbId, tmdbId, season, episode, rawId };
}

async function resolveMetadata(type, rawId) {
  const isSeries = type === "series" || type === "tv";
  const mediaType = isSeries ? "series" : "movie";
  const { imdbId, tmdbId, season, episode } = parseStreamId(rawId);

  const cacheKey = `meta:${mediaType}:${rawId}`;
  const cached = metaCache.get(cacheKey);
  if (cached) return cached;

  let title = null;
  let year = null;
  let resolvedImdbId = imdbId;
  let episodeTitle = null;

  // 1. Try Cinemeta with redirect following
  if (imdbId) {
    try {
      const cinemetaUrl = `${CINEMETA_BASE}/meta/${mediaType}/${imdbId}.json`;
      const res = await nodeFetch(cinemetaUrl, {
        timeout: 5000,
        redirect: "follow",
        headers: { "User-Agent": "KHDiamond-Stremio/1.0" }
      });

      if (res.ok) {
        const data = await res.json();
        const meta = data && data.meta;
        if (meta && meta.name) {
          title = meta.name;
          const matchYear = String(meta.year || meta.releaseInfo || "").match(/\b(19\d\d|20\d\d)\b/);
          year = matchYear ? parseInt(matchYear[1], 10) : null;

          if (isSeries && season !== null && episode !== null && Array.isArray(meta.videos)) {
            const ep = meta.videos.find((v) => v.season === season && v.episode === episode);
            if (ep) episodeTitle = ep.name || ep.title || null;
          }
        }
      }
    } catch (_) {}
  }

  // 2. Try TMDB find by IMDb ID if title still unresolved
  if (!title && imdbId) {
    try {
      const findUrl = `https://api.themoviedb.org/3/find/${imdbId}?api_key=${getTmdbKey()}&external_source=imdb_id`;
      const res = await nodeFetch(findUrl, { timeout: 5000 });
      if (res.ok) {
        const data = await res.json();
        const item = isSeries
          ? data.tv_results?.[0]
          : data.movie_results?.[0];
        if (item) {
          title = item.title || item.name;
          const relDate = item.release_date || item.first_air_date || "";
          const matchYear = relDate.match(/\b(19\d\d|20\d\d)\b/);
          year = matchYear ? parseInt(matchYear[1], 10) : null;
        }
      }
    } catch (_) {}
  }

  // 3. Try TMDB by tmdbId if present
  if (!title && tmdbId) {
    try {
      const tmdbType = isSeries ? "tv" : "movie";
      const tmdbUrl = `https://api.themoviedb.org/3/${tmdbType}/${tmdbId}?api_key=${getTmdbKey()}`;
      const res = await nodeFetch(tmdbUrl, {
        timeout: 5000,
        headers: { Accept: "application/json" }
      });

      if (res.ok) {
        const data = await res.json();
        title = data.title || data.name;
        const relDate = data.release_date || data.first_air_date || "";
        const matchYear = relDate.match(/\b(19\d\d|20\d\d)\b/);
        year = matchYear ? parseInt(matchYear[1], 10) : null;
        if (!resolvedImdbId && data.imdb_id) {
          resolvedImdbId = data.imdb_id;
        }
      }
    } catch (_) {}
  }

  const result = {
    rawId,
    type: mediaType,
    isSeries,
    imdbId: resolvedImdbId,
    tmdbId,
    title,
    year,
    season,
    episode,
    episodeTitle
  };

  if (title) {
    metaCache.set(cacheKey, result, 86400);
  }

  return result;
}

module.exports = {
  parseStreamId,
  resolveMetadata
};
