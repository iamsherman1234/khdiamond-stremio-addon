"use strict";

const packageJson = require("./package.json");

module.exports = {
  id: "community.khdiamond.stream",
  version: packageJson.version || "1.0.0",
  name: "KHDiamond Khmer Dubbed",
  description: "Stream Khmer dubbed movies and series directly from KHDiamond with ultra-fast CDN delivery.",
  logo: "https://khdiamond.net/wp-content/uploads/2025/02/khdiamond-logo.png",
  background: "https://khdiamond.net/wp-content/uploads/2025/02/khdiamond-logo.png",
  resources: ["catalog", "meta", "stream"],
  types: ["movie", "series"],
  idPrefixes: ["khd:", "tt", "tmdb:"],
  catalogs: [
    {
      type: "movie",
      id: "khd_unlocked",
      name: "KHDiamond Unlocked Library (រឿងដែលបានទិញ)",
      extra: [
        { name: "skip", isRequired: false }
      ]
    },
    {
      type: "movie",
      id: "khd_movies",
      name: "KHDiamond Movies (រឿងដុំ)",
      extra: [
        { name: "search", isRequired: false },
        { name: "skip", isRequired: false }
      ]
    },
    {
      type: "series",
      id: "khd_series",
      name: "KHDiamond Series (រឿងភាគ)",
      extra: [
        { name: "search", isRequired: false },
        { name: "skip", isRequired: false }
      ]
    }
  ],
  behaviorHints: {
    configurable: false,
    configurationRequired: false
  }
};
