"use strict";

require("dotenv").config();
const { FlareSolverrClient } = require("./lib/flaresolverr");
const { KhdiamondScraper } = require("./lib/scraper");

async function runTest() {
  console.log("=== Testing KHDiamond Stremio Scraper & FlareSolverr ===");
  console.log(`Target Site: ${process.env.SITE_URL}`);
  console.log(`FlareSolverr: ${process.env.FLARESOLVERR_URL}`);

  const flaresolverr = new FlareSolverrClient();
  const scraper = new KhdiamondScraper(flaresolverr);

  try {
    console.log("\n[1/3] Testing catalog scraping (/movies)...");
    const movies = await scraper.getCatalog("movie", { skip: 0 });
    console.log(`Found ${movies.length} movies in catalog.`);
    if (movies.length > 0) {
      console.log("Sample movie:", JSON.stringify(movies[0], null, 2));

      console.log("\n[2/3] Testing metadata resolution for first movie...");
      const sampleId = movies[0].id;
      const meta = await scraper.getMeta("movie", sampleId);
      console.log("Movie metadata resolved:", JSON.stringify({
        id: meta.id,
        name: meta.name,
        releaseInfo: meta.releaseInfo,
        genres: meta.genres,
        descriptionLength: meta.description ? meta.description.length : 0,
      }, null, 2));

      console.log("\n[3/3] Testing stream extraction...");
      const streams = await scraper.getStreams("movie", sampleId);
      console.log(`Found ${streams.length} stream(s):`);
      console.log(JSON.stringify(streams, null, 2));
    } else {
      console.warn("Catalog returned 0 items. Check page structure or cookie authentication.");
    }

    console.log("\n=== Test complete ===");
  } catch (err) {
    console.error("\n[!] Test failed with error:", err.message);
  } finally {
    await flaresolverr.destroySession();
  }
}

runTest();
