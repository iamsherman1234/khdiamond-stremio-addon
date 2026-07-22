require("dotenv").config();
const { addonBuilder, serveHTTP } = require("stremio-addon-sdk");
const fs = require("fs");
const path = require("path");

const PORT = parseInt(process.env.PORT || "7002");
const ADDON_URL = process.env.ADDON_URL || ("http://localhost:" + PORT);
const CATALOG_PATH = process.env.CATALOG_PATH || "./catalog.json";

const MF_PRIMARY   = process.env.MEDIAFLOW_URL     || "https://sudolocal.qzz.io/mediaflow-py";
const MF_FALLBACK  = process.env.MEDIAFLOW_URL2    || "https://mediaflow-proxy-l98z.onrender.com";
const MF_PASSWORD  = process.env.MEDIAFLOW_PASSWORD || "";

const CDN_URLS = [
  "https://media-1.khdmcloud.online/hls/{movie_id}/{quality}.m3u8",
  "https://khdiamondcdn.asia/hls/{movie_id}/{quality}.m3u8",
  "https://khdm-media.tripplestream.online/hls/{movie_id}/{quality}.m3u8",
];

const MF_SERVERS = [
  { base: MF_PRIMARY,  label: "S10" },
  { base: MF_FALLBACK, label: "Cloud" },
].filter(function(s) { return Boolean(s.base); });

let catalogCache = { path: "", mtimeMs: 0, items: [] };

function loadCatalog() {
  try {
    const resolvedPath = path.resolve(CATALOG_PATH);
    const stat = fs.statSync(resolvedPath);
    if (catalogCache.path === resolvedPath && catalogCache.mtimeMs === stat.mtimeMs) {
      return catalogCache.items;
    }
    const raw = fs.readFileSync(resolvedPath, "utf-8");
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      throw new Error("catalog root must be an array");
    }
    catalogCache = { path: resolvedPath, mtimeMs: stat.mtimeMs, items: parsed };
    return parsed;
  } catch (e) {
    console.error("Could not load catalog.json:", e.message);
    return [];
  }
}

function getCatalog() {
  return loadCatalog();
}

function makeProxyUrl(mfBase, originalUrl) {
  if (!MF_PASSWORD) return "";
  return mfBase + "/proxy/hls/manifest.m3u8" +
    "?api_password=" + encodeURIComponent(MF_PASSWORD) +
    "&d=" + encodeURIComponent(originalUrl);
}

function normalizeImdbId(id) {
  if (!id) return "";
  const value = String(id).trim();
  if (!value) return "";
  return value.startsWith("tt") ? value : "tt" + value.replace(/^tt/, "");
}

function itemMatchesId(item, id) {
  return item.khd_id === id || normalizeImdbId(item.imdb_id) === id;
}

const manifest = {
  id: "com.khdiamond.khmer",
  version: "1.0.0",
  name: "KhDiamond",
  description: "Khmer dubbed movies from KhDiamond - your personal purchased library.",
  logo: "https://khdiamond.net/wp-content/uploads/2025/02/khdiamond-logo.png",
  resources: ["catalog", "meta", "stream"],
  types: ["movie", "series"],
  idPrefixes: ["khd_", "tt"],
  catalogs: [
    {
      type: "movie",
      id: "khdiamond_movies",
      name: "KhDiamond Movies",
      extra: [{ name: "search", isRequired: false }],
    },
    {
      type: "series",
      id: "khdiamond_series",
      name: "KhDiamond Series",
      extra: [{ name: "search", isRequired: false }],
    },
  ],
  behaviorHints: {
    adult: false,
    p2p: false,
    configurable: false,
    configurationRequired: false,
  },
};

const builder = new addonBuilder(manifest);

builder.defineCatalogHandler(function({ type, id, extra }) {
  const catalog = getCatalog();
  const search = (extra && extra.search ? extra.search : "").toLowerCase().trim();
  let items = catalog.filter(function(m) { return m.type === type; });
  if (search) {
    items = items.filter(function(m) {
      return (m.title_english || "").toLowerCase().includes(search) ||
             (m.title_khmer || "").toLowerCase().includes(search) ||
             (m.slug || "").toLowerCase().includes(search);
    });
  }
  const metas = items.map(function(m) {
    const imdbId = normalizeImdbId(m.imdb_id);
    return {
      id: imdbId || m.khd_id,
      type: m.type,
      name: m.title_english,
      poster: m.poster || "",
      background: m.backdrop || "",
      description: m.overview || "",
      year: m.year || "",
      imdbRating: m.imdb_rating || "",
      genres: m.genres || [],
    };
  });
  return Promise.resolve({ metas: metas });
});

builder.defineMetaHandler(function({ type, id }) {
  if (!id.startsWith("khd_") && !id.startsWith("tt")) return Promise.resolve({ meta: null });
  const catalog = getCatalog();
  const item = catalog.find(function(m) { return itemMatchesId(m, id); });
  if (!item) return Promise.resolve({ meta: null });
  const desc = (item.title_khmer ? item.title_khmer + "\n\n" : "") + (item.overview || "");
  const imdbId = normalizeImdbId(item.imdb_id);
  const meta = {
    id: imdbId || item.khd_id,
    type: item.type,
    name: item.title_english,
    poster: item.poster || "",
    background: item.backdrop || "",
    description: desc.trim(),
    year: item.year || "",
    imdbRating: item.imdb_rating || "",
    genres: item.genres || [],
  };
  return Promise.resolve({ meta: meta });
});

builder.defineStreamHandler(function({ type, id }) {
  if (!id.startsWith("khd_") && !id.startsWith("tt")) return Promise.resolve({ streams: [] });
  if (!MF_PASSWORD) return Promise.resolve({ streams: [] });
  const catalog = getCatalog();
  const item = catalog.find(function(m) { return itemMatchesId(m, id); });
  if (!item || !item.movie_id) return Promise.resolve({ streams: [] });

  const streams = [];
  const title = item.title_khmer || item.title_english;

  const qualities = [];

  // Build quality list
  if (item.movie_id_4k) {
    qualities.push({ label: "4K (2160p)", quality: "2160p", movie_id: item.movie_id_4k, name: "KhDiamond 4K" });
  }
  qualities.push({ label: "1080p", quality: "1080p", movie_id: item.movie_id, name: "KhDiamond" });
  qualities.push({ label: "720p",  quality: "720p",  movie_id: item.movie_id, name: "KhDiamond" });

  // For each quality × CDN × MediaFlow
  for (const q of qualities) {
    for (let c = 0; c < CDN_URLS.length; c++) {
      const cdnLabel = c === 0 ? "CDN1" : "CDN2";
      const originalUrl = CDN_URLS[c]
        .replace("{movie_id}", q.movie_id)
        .replace("{quality}", q.quality);

      for (const mf of MF_SERVERS) {
        const url = makeProxyUrl(mf.base, originalUrl);
        if (!url) continue;
        streams.push({
          url: url,
          name: q.name,
          title: q.label + " | " + cdnLabel + " | " + mf.label + "\n" + title,
          behaviorHints: { notWebReady: false },
        });
      }
    }
  }

  return Promise.resolve({ streams: streams });
});

const addonInterface = builder.getInterface();
serveHTTP(addonInterface, { port: PORT, staticPath: false });

console.log("KhDiamond Stremio Addon");
console.log("Local  : http://localhost:" + PORT + "/manifest.json");
console.log("Public : " + ADDON_URL + "/manifest.json");
console.log("Catalog: " + path.resolve(CATALOG_PATH));
console.log("MediaFlow Primary : " + MF_PRIMARY);
console.log("MediaFlow Fallback: " + MF_FALLBACK);
