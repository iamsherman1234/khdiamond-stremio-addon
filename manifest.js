"use strict";

module.exports = {
  id: "community.khdiamond.stream",
  version: "1.0.0",
  name: "KHDiamond Khmer Dubbed",
  description: "Stream Khmer dubbed movies and series directly from KHDiamond.",
  logo: "https://khdiamond.net/wp-content/uploads/2023/01/cropped-logo-192x192.png",
  background: "https://khdiamond.net/wp-content/uploads/2023/01/cropped-logo-192x192.png",
  resources: ["catalog", "meta", "stream"],
  types: ["movie", "series"],
  idPrefixes: ["khd:"],
  catalogs: [
    {
      type: "movie",
      id: "khd_movies",
      name: "KHDiamond Movies",
      extra: [
        { name: "search", isRequired: false },
        { name: "skip", isRequired: false }
      ]
    },
    {
      type: "series",
      id: "khd_series",
      name: "KHDiamond Series",
      extra: [
        { name: "search", isRequired: false },
        { name: "skip", isRequired: false }
      ]
    }
  ]
};
