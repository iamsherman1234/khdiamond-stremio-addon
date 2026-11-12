"use strict";

/**
 * Common unpacker for eval(function(p,a,c,k,e,d)...) packed scripts
 */
function unpackPacker(packedCode) {
  try {
    const match = packedCode.match(/}\s*\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*)'\.split\('\|'\)/);
    if (!match) return null;

    let [, p, aStr, cStr, kStr] = match;
    let a = parseInt(aStr, 10);
    let c = parseInt(cStr, 10);
    const k = kStr.split("|");

    function e(c) {
      return (c < a ? "" : e(Math.floor(c / a))) + ((c = c % a) > 35 ? String.fromCharCode(c + 29) : c.toString(36));
    }

    const dict = {};
    while (c--) {
      dict[e(c)] = k[c] || e(c);
    }

    return p.replace(/\b(\w+)\b/g, (match) => dict[match] || match);
  } catch (err) {
    return null;
  }
}

/**
 * Extract stream targets from direct URLs or page contents
 */
async function extractStreamsFromHtml(html, pageUrl) {
  const streams = [];

  // 1. Direct regex scan for m3u8 or mp4
  const m3u8Regex = /(https?:\/\/[^\s"'<>]+\.m3u8[^\s"'<>]*)/gi;
  const mp4Regex = /(https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*)/gi;

  let match;
  while ((match = m3u8Regex.exec(html)) !== null) {
    const url = match[1].replace(/\\/g, "");
    if (!streams.some((s) => s.url === url)) {
      streams.push({
        name: "KHDiamond [HLS]",
        title: "Khmer Dubbed - HLS Stream",
        url,
        behaviorHints: {
          notWebReady: false,
        },
      });
    }
  }

  while ((match = mp4Regex.exec(html)) !== null) {
    const url = match[1].replace(/\\/g, "");
    if (!streams.some((s) => s.url === url)) {
      streams.push({
        name: "KHDiamond [MP4]",
        title: "Khmer Dubbed - Direct MP4",
        url,
      });
    }
  }

  // 2. Scan for packed scripts
  const packedMatch = html.match(/eval\(function\(p,a,c,k,e,d[\s\S]*?\.split\('\|'\)\)\)/g);
  if (packedMatch) {
    for (const packed of packedMatch) {
      const unpacked = unpackPacker(packed);
      if (unpacked) {
        while ((match = m3u8Regex.exec(unpacked)) !== null) {
          const url = match[1].replace(/\\/g, "");
          if (!streams.some((s) => s.url === url)) {
            streams.push({
              name: "KHDiamond [HLS]",
              title: "Khmer Dubbed - HLS (Unpacked)",
              url,
            });
          }
        }
      }
    }
  }

  // 3. Scan for Pixeldrain URLs
  const pixeldrainRegex = /https?:\/\/pixeldrain\.com\/(?:u|api\/file)\/([a-zA-Z0-9_-]+)/g;
  while ((match = pixeldrainRegex.exec(html)) !== null) {
    const fileId = match[1];
    const streamUrl = `https://pixeldrain.com/api/file/${fileId}`;
    if (!streams.some((s) => s.url === streamUrl)) {
      streams.push({
        name: "KHDiamond [Pixeldrain]",
        title: `Pixeldrain - ${fileId}`,
        url: streamUrl,
      });
    }
  }

  return streams;
}

module.exports = {
  unpackPacker,
  extractStreamsFromHtml,
};
