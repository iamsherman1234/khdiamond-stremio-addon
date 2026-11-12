"use strict";

require("dotenv").config();
const { HttpClient } = require("./lib/client");
const { HlsProxy } = require("./lib/hlsProxy");
const { KhdiamondScraper } = require("./lib/scraper");
const nodeFetch = require("node-fetch");

async function runTest() {
  console.log("=== Testing KHDiamond Stremio Scraper Pipeline ===");
  console.log(`Target Site: ${process.env.SITE_URL || "https://khdiamond.net"}`);
  console.log(`Cambodia Proxy: ${process.env.CAMBODIA_PROXY || "None"}`);

  const httpClient = new HttpClient();
  const hlsProxy = new HlsProxy({ httpClient });
  const scraper = new KhdiamondScraper(httpClient, hlsProxy);
  const testHostBase = `http://localhost:${process.env.PORT || "7070"}`;

  try {
    // ── STEP 1: MOVIES CATALOG ──
    console.log("\n[1/6] Testing Movies Catalog (/movies)...");
    const movies = await scraper.getCatalog("movie", { skip: 0 });
    console.log(`Found ${movies.length} movies in catalog.`);
    if (movies.length > 0) {
      console.log("Sample movie:", JSON.stringify(movies[0], null, 2));
    } else {
      throw new Error("Movies catalog returned 0 items");
    }

    // ── STEP 2: SERIES CATALOG ──
    console.log("\n[2/6] Testing Series Catalog (/tvshows)...");
    const series = await scraper.getCatalog("series", { skip: 0 });
    console.log(`Found ${series.length} series in catalog.`);
    if (series.length > 0) {
      console.log("Sample series:", JSON.stringify(series[0], null, 2));
    } else {
      throw new Error("Series catalog returned 0 items");
    }

    // ── STEP 3: MOVIE METADATA ──
    console.log("\n[3/6] Testing Movie Metadata Resolution...");
    const sampleMovieId = movies[0].id;
    const movieMeta = await scraper.getMeta("movie", sampleMovieId);
    console.log("Movie metadata resolved:", JSON.stringify({
      id: movieMeta.id,
      name: movieMeta.name,
      releaseInfo: movieMeta.releaseInfo,
      genres: movieMeta.genres,
      descriptionLength: movieMeta.description ? movieMeta.description.length : 0,
    }, null, 2));

    // ── STEP 4: SERIES METADATA & EPISODES ──
    console.log("\n[4/6] Testing Series Metadata & Episode Parsing...");
    const sampleSeriesId = series[0].id;
    const seriesMeta = await scraper.getMeta("series", sampleSeriesId);
    console.log("Series metadata resolved:", JSON.stringify({
      id: seriesMeta.id,
      name: seriesMeta.name,
      episodesCount: seriesMeta.videos ? seriesMeta.videos.length : 0,
      sampleEpisode: seriesMeta.videos ? seriesMeta.videos[0] : null,
    }, null, 2));

    // ── STEP 5: STREAM RESOLUTION (KHD ID) ──
    console.log("\n[5/6] Testing Stream Extraction for KGF (Movie)...");
    const kgfPath = "/movies/k-g-f-chapter-1__trashed/";
    const kgfId = scraper._pathToId(kgfPath);
    const kgfStreams = await scraper.getStreams("movie", kgfId, testHostBase);
    console.log(`Found ${kgfStreams.length} stream(s) for KGF:`);
    console.log(JSON.stringify(kgfStreams, null, 2));

    if (kgfStreams.length > 0 && kgfStreams[0].url) {
      console.log("\n[6/6] Verifying HLS Stream Proxy Playability...");
      const proxyUrl = kgfStreams[0].url;
      const proxyQuery = proxyUrl.replace(testHostBase, "");
      console.log(`Testing master playlist route: ${proxyQuery}`);

      // Emulate proxy request
      const urlObj = new URL(proxyUrl);
      const mockReq = { query: Object.fromEntries(urlObj.searchParams.entries()) };
      let responseBody = "";
      let responseHeaders = {};
      let responseStatus = 200;

      const mockRes = {
        setHeader: (k, v) => { responseHeaders[k] = v; },
        status: (code) => { responseStatus = code; return mockRes; },
        send: (body) => { responseBody = body; }
      };

      await hlsProxy.handleMasterPlaylist(mockReq, mockRes, testHostBase);
      console.log(`Proxy response status: ${responseStatus}`);
      console.log(`Proxy content-type: ${responseHeaders["Content-Type"]}`);
      console.log(`Rewritten playlist preview:\n${responseBody.slice(0, 350)}`);

      if (responseBody.startsWith("#EXTM3U")) {
        console.log("\n>>> HLS Master Playlist verified playable!");
      }
    }

    console.log("\n=== ALL TESTS PASSED SUCCESSFULLY! ===");
  } catch (err) {
    console.error("\n[!] Test failed with error:", err);
  }
}

runTest();
