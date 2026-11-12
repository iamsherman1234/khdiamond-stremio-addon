"use strict";

require("dotenv").config();
const cheerio = require("cheerio");
const { FlareSolverrClient } = require("./lib/flaresolverr");

async function countMedia() {
  console.log("Connecting to FlareSolverr to check total catalog counts...");
  const client = new FlareSolverrClient();

  try {
    // 1. Inspect navigation links from main page to find actual categories
    console.log("Checking navigation menu for series/drama categories...");
    const homeRes = await client.get(`${process.env.SITE_URL || "https://khdiamond.net"}/movies/`);
    const $home = cheerio.load(homeRes.html);
    const navLinks = [];
    $home("nav a, .menu a, header a").each((_, el) => {
      const href = $home(el).attr("href");
      const text = $home(el).text().trim();
      if (href && text && !href.startsWith("#")) {
        navLinks.push({ text, href });
      }
    });
    console.log("Found nav menu links:");
    const seenHrefs = new Set();
    for (const l of navLinks) {
      if (!seenHrefs.has(l.href) && (l.href.includes("khdiamond.net") || l.href.startsWith("/"))) {
        seenHrefs.add(l.href);
        console.log(`  - ${l.text}: ${l.href}`);
      }
    }

    for (const section of ["movies"]) {
      const url = `${process.env.SITE_URL || "https://khdiamond.net"}/${section}/`;
      console.log(`\nInspecting ${section} catalog: ${url}`);
      
      const res = await client.get(url);
      const $ = cheerio.load(res.html);

      // Count items on the first page
      const itemsOnPage = $("article.item, article.post, .TPost, .movie-item, .film-detail, .item.movies, .item.tvshows, div.post").length;

      // Log raw pagination text and HTML for debugging
      const rawPaginationHtml = $(".pagination, .nav-links, .pages, .wp-pagenavi").html() || "";
      const rawPaginationText = $(".pagination, .nav-links, .pages, .wp-pagenavi").text().trim();
      
      let totalPages = 1;

      // Extract page numbers individually from links
      const pageNumbers = [];
      $(".page-numbers, .pagination a, .pagination span, .nav-links a").each((_, el) => {
        const txt = $(el).text().trim();
        const num = parseInt(txt, 10);
        if (!isNaN(num) && String(num) === txt) {
          pageNumbers.push(num);
        }
        // Also check href for /page/(\d+)
        const href = $(el).attr("href") || "";
        const hrefMatch = href.match(/\/page\/(\d+)\/?/);
        if (hrefMatch) {
          pageNumbers.push(parseInt(hrefMatch[1], 10));
        }
      });

      if (pageNumbers.length > 0) {
        totalPages = Math.max(...pageNumbers);
      } else {
        const match = rawPaginationText.match(/of\s+(\d+)/i) || rawPaginationText.match(/\/\s*(\d+)/);
        if (match) totalPages = parseInt(match[1], 10);
      }

      console.log(`--- [${section.toUpperCase()}] ---`);
      console.log(`Pagination Text: "${rawPaginationText}"`);
      console.log(`Items per page: ${itemsOnPage}`);
      console.log(`Total pages: ${totalPages}`);
      console.log(`Total count: ~${totalPages * itemsOnPage} titles`);
    }
  } catch (err) {
    console.error("Error inspecting counts:", err.message);
  } finally {
    await client.destroySession();
  }
}

countMedia();
