"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");

function normalizeTitleKey(str) {
  if (!str) return "";
  return String(str)
    .replace(/[\u200B-\u200D\uFEFF]/g, "") // strip zero-width spaces/joiners
    .replace(/\s+/g, " ")                  // collapse multiple whitespace
    .trim()
    .toLowerCase();
}

class GDriveManager {
  constructor(options = {}) {
    this.dataDir = options.dataDir || path.resolve(__dirname, "..", "data");
    this.indexPath = options.indexPath || process.env.GDRIVE_INDEX_PATH || "";
    this.mountPath = options.mountPath || process.env.GDRIVE_MOUNT_PATH || "";
    this.folderIds = String(options.folderId || process.env.GDRIVE_FOLDER_ID || "")
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    this.apiKeys = String(options.apiKey || process.env.GDRIVE_API_KEY || "")
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    this.keyIndex = 0;
    this.index = new Map();
    this.reloadIndex();

    // Auto-fetch from Google Drive Cloud folder if configured
    if (this.folderIds.length && this.apiKeys.length && options.autoScan !== false) {
      this.fetchRemoteDriveFolder().catch((err) => {
        console.warn(`[GDrive] Initial cloud folder scan warning: ${err.message}`);
      });
      // Periodically refresh every 5 minutes to pick up newly downloaded movies
      setInterval(() => {
        this.fetchRemoteDriveFolder().catch(() => {});
      }, 5 * 60 * 1000).unref();
    }
  }

  getApiKey() {
    if (!this.apiKeys.length) return "";
    const key = this.apiKeys[this.keyIndex % this.apiKeys.length];
    this.keyIndex++;
    return key;
  }

  _addIndex(key, item) {
    if (!key) return;
    const raw = String(key).trim();
    if (!raw) return;
    this.index.set(raw, item);
    const lower = raw.toLowerCase();
    this.index.set(lower, item);
    const norm = normalizeTitleKey(raw);
    if (norm) {
      this.index.set(norm, item);
      const withoutExt = norm.replace(/\.(mp4|mkv|webm|avi|ts)$/i, "");
      if (withoutExt) {
        this.index.set(withoutExt, item);

        // Pattern: "Three.Kingdoms.2010.S01E66.1080p.KhmerDub" or "Show Name S01E05"
        const epMatch = withoutExt.match(/^(.+?)[\s._-]+s(\d+)[\s._-]*e(\d+)/i);
        if (epMatch) {
          const showRaw = epMatch[1].replace(/\b(19\d\d|20\d\d)\b/g, "").replace(/[._]/g, " ").trim();
          const sNum = parseInt(epMatch[2], 10);
          const eNum = parseInt(epMatch[3], 10);
          const sTitle = normalizeTitleKey(showRaw);
          this.index.set(`${sTitle}_s${sNum}_e${eNum}`, item);
          this.index.set(`${sTitle} s${sNum}e${eNum}`, item);
          this.index.set(`${sTitle} e${eNum}`, item);
          this.index.set(`${sTitle} ភាគ${eNum}`, item);
          this.index.set(`${sTitle} ភាគ ${eNum}`, item);
        }

        // Pattern: "Show Name ភាគ 01" or "Show Name ភាគ1"
        const khmerEpMatch = withoutExt.match(/^(.+?)[\s._-]+ភាគ[\s._-]*(\d+)/i);
        if (khmerEpMatch) {
          const showRaw = khmerEpMatch[1].trim();
          const eNum = parseInt(khmerEpMatch[2], 10);
          const sTitle = normalizeTitleKey(showRaw);
          this.index.set(`${sTitle}_s1_e${eNum}`, item);
          this.index.set(`${sTitle} s1e${eNum}`, item);
          this.index.set(`${sTitle} e${eNum}`, item);
          this.index.set(`${sTitle} ភាគ${eNum}`, item);
          this.index.set(`${sTitle} ភាគ ${eNum}`, item);
        }
      }
    }
  }

  reloadIndex() {
    this.index.clear();

    const candidatePaths = [
      this.indexPath,
      path.join(this.dataDir, "sabay_gdrive_sync.json"),
      path.join(this.dataDir, "pixeldrain_gdrive_sync.json"),
      path.join(this.dataDir, "khdiamond_gdrive_sync.json"),
      path.join(this.dataDir, "gdrive_index.json"),
      path.join(__dirname, "..", "sabay_gdrive_sync.json"),
      path.join(__dirname, "..", "pixeldrain_gdrive_sync.json"),
      path.join(__dirname, "..", "khdiamond_gdrive_sync.json")
    ].filter(Boolean);

    for (const p of candidatePaths) {
      if (fs.existsSync(p)) {
        try {
          const raw = JSON.parse(fs.readFileSync(p, "utf8"));
          const uploaded = raw.uploaded || raw;
          for (const [hashOrId, info] of Object.entries(uploaded)) {
            if (typeof info === "object" && info) {
              const item = {
                hash: hashOrId,
                filename: info.filename || path.basename(info.dest_path || ""),
                destPath: info.dest_path || "",
                fileId: info.file_id || info.fileId || "",
                sizeMb: info.size_mb || 0,
                webUrl: info.web_url || info.webUrl || ""
              };
              this._addIndex(hashOrId, item);
              if (item.filename) {
                this._addIndex(item.filename, item);
              }
            }
          }
          console.log(`[GDrive] Loaded ${this.index.size} records from local ${p}`);
        } catch (e) {
          console.warn(`[GDrive] Error parsing index ${p}: ${e.message}`);
        }
      }
    }

    if (this.mountPath && fs.existsSync(this.mountPath)) {
      try {
        const files = fs.readdirSync(this.mountPath);
        for (const file of files) {
          const full = path.join(this.mountPath, file);
          const stat = fs.statSync(full);
          if (stat.isFile() && file.endsWith(".mp4")) {
            const item = {
              filename: file,
              destPath: full,
              sizeMb: Math.round(stat.size / (1024 * 1024)),
              localFile: true
            };
            this._addIndex(file, item);
          }
        }
        console.log(`[GDrive] Indexed ${files.length} local files from mount ${this.mountPath}`);
      } catch (e) {
        console.warn(`[GDrive] Could not read mount path ${this.mountPath}: ${e.message}`);
      }
    }
  }

  async fetchRemoteDriveFolder() {
    if (!this.folderIds.length || !this.apiKeys.length) return;

    let totalCloudFiles = 0;

    for (const folderId of this.folderIds) {
      try {
        let pageToken = "";
        const files = [];

        do {
          const currentKey = this.getApiKey();
          const q = encodeURIComponent(`'${folderId}' in parents and trashed = false`);
          let url = `https://www.googleapis.com/drive/v3/files?q=${q}&key=${currentKey}&fields=nextPageToken,files(id,name,size,mimeType)&pageSize=1000`;
          if (pageToken) url += `&pageToken=${encodeURIComponent(pageToken)}`;

          const res = await fetch(url);
          if (!res.ok) {
            throw new Error(`Drive API folder ${folderId} status ${res.status}: ${res.statusText}`);
          }

          const data = await res.json();
          const pageFiles = data.files || [];
          files.push(...pageFiles);
          pageToken = data.nextPageToken || "";
        } while (pageToken);

        totalCloudFiles += files.length;
        const driveFilesByName = new Map();

        for (const f of files) {
          if (f.name && f.id) {
            driveFilesByName.set(f.name.toLowerCase(), f);
            const titleKey = f.name.replace(/\.mp4$/i, "").toLowerCase();
            driveFilesByName.set(titleKey, f);
            const normKey = normalizeTitleKey(f.name.replace(/\.mp4$/i, ""));
            if (normKey) driveFilesByName.set(normKey, f);
          }
        }

        // Check if any sync registries exist in Drive folder
        const syncFiles = files.filter((f) =>
          f.name === "sabay_gdrive_sync.json" ||
          f.name === "khdiamond_gdrive_sync.json" ||
          f.name === "pixeldrain_gdrive_sync.json" ||
          f.name === "gdrive_index.json"
        );
        for (const syncFile of syncFiles) {
          try {
            const syncUrl = `https://drive.usercontent.google.com/download?id=${syncFile.id}&export=download&authuser=0&confirm=t`;
            const syncRes = await fetch(syncUrl);
            if (syncRes.ok) {
              const syncData = await syncRes.json();
              const uploaded = syncData.uploaded || syncData;
              for (const [hash, info] of Object.entries(uploaded)) {
                if (typeof info === "object" && info) {
                  const fn = info.filename || path.basename(info.dest_path || "");
                  const matchedDrive = driveFilesByName.get(fn.toLowerCase()) ||
                    driveFilesByName.get(fn.replace(/\.mp4$/i, "").toLowerCase()) ||
                    driveFilesByName.get(normalizeTitleKey(fn.replace(/\.mp4$/i, "")));
                  const item = {
                    hash,
                    filename: fn,
                    fileId: matchedDrive ? matchedDrive.id : (info.file_id || ""),
                    sizeMb: matchedDrive ? Math.round(Number(matchedDrive.size || 0) / (1024 * 1024)) : (info.size_mb || 0)
                  };
                  this._addIndex(hash, item);
                  this._addIndex(fn, item);
                }
              }
            }
          } catch (e) {
            console.warn(`[GDrive] Error parsing remote ${syncFile.name}: ${e.message}`);
          }
        }

        // Index all video files in folder by title/filename (.mp4, .mkv, .webm, etc.)
        for (const f of files) {
          const fn = f.name || "";
          if (Number(f.size || 0) <= 0) continue; // skip empty or corrupt 0-byte files
          if (/\.(mp4|mkv|webm|avi|ts)$/i.test(fn) || (f.mimeType && f.mimeType.startsWith("video/"))) {
            const item = {
              filename: fn,
              fileId: f.id,
              sizeMb: Math.round(Number(f.size || 0) / (1024 * 1024))
            };
            this._addIndex(fn, item);
          }
        }
      } catch (err) {
        console.warn(`[GDrive Cloud] Folder ${folderId} scan error: ${err.message}`);
      }
    }

    console.log(`[GDrive Cloud] Active index: ${this.index.size} entries mapped from Google Drive (${totalCloudFiles} cloud files).`);
  }

  findItem(hash, title = "", episodeInfo = null) {
    // 1. Episode-specific lookup
    if (episodeInfo && (episodeInfo.number !== undefined || episodeInfo.episode !== undefined)) {
      if (episodeInfo.hash && this.index.has(episodeInfo.hash)) {
        return this.index.get(episodeInfo.hash);
      }
      if (episodeInfo.title) {
        const epNorm = normalizeTitleKey(episodeInfo.title);
        if (this.index.has(epNorm)) return this.index.get(epNorm);
      }

      const epNum = episodeInfo.number !== undefined ? Number(episodeInfo.number) : Number(episodeInfo.episode);
      const sNum = episodeInfo.season !== undefined ? Number(episodeInfo.season) : 1;
      const cleanTitle = normalizeTitleKey(title);

      const candidateKeys = [
        `${cleanTitle}_s${sNum}_e${epNum}`,
        `${cleanTitle} s${sNum}e${epNum}`,
        `${cleanTitle} e${epNum}`,
        `${cleanTitle} episode ${epNum}`,
        `${cleanTitle} ភាគ ${epNum}`,
        `${cleanTitle} ភាគ${epNum}`,
      ];

      for (const k of candidateKeys) {
        if (k && this.index.has(k)) return this.index.get(k);
      }
    }

    // 2. Hash direct lookup
    if (hash && this.index.has(hash)) return this.index.get(hash);

    // 3. Normalized title direct lookup
    if (title) {
      const norm = normalizeTitleKey(title);
      if (this.index.has(norm)) return this.index.get(norm);
      const withoutExt = norm.replace(/\.(mp4|mkv|webm|avi|ts)$/i, "");
      if (withoutExt && this.index.has(withoutExt)) return this.index.get(withoutExt);

      // Try title without parentheses e.g. "Movie Name (2024)" -> "Movie Name"
      const withoutParen = norm.replace(/\s*\([^)]*\)/g, "").trim();
      if (withoutParen && this.index.has(withoutParen)) return this.index.get(withoutParen);

      // 4. Substring fallback match
      if (norm.length > 3) {
        for (const [k, item] of this.index.entries()) {
          if (k.length > 3 && (k.includes(norm) || norm.includes(k))) {
            return item;
          }
        }
      }
    }
    return null;
  }
}

function streamLocalFile(filePath, req, res) {
  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: "Local file not found" });
  }

  const stat = fs.statSync(filePath);
  const total = stat.size;
  const range = req.headers.range;

  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Accept-Ranges", "bytes");

  if (range) {
    const parts = range.replace(/bytes=/, "").split("-");
    const start = parseInt(parts[0], 10);
    const end = parts[1] ? parseInt(parts[1], 10) : total - 1;
    const chunkSize = end - start + 1;

    res.writeHead(206, {
      "Content-Range": `bytes ${start}-${end}/${total}`,
      "Content-Length": chunkSize,
      "Content-Type": "video/mp4"
    });
    fs.createReadStream(filePath, { start, end }).pipe(res);
  } else {
    res.writeHead(200, {
      "Content-Length": total,
      "Content-Type": "video/mp4"
    });
    fs.createReadStream(filePath).pipe(res);
  }
}

function streamGDriveProxy(fileId, req, res, apiKeyInput = "") {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader("Accept-Ranges", "bytes");

  const keys = String(apiKeyInput || process.env.GDRIVE_API_KEY || "")
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  let keyIndex = 0;

  function getTargetUrl() {
    return `https://drive.usercontent.google.com/download?id=${fileId}&export=download&authuser=0&confirm=t`;
  }

  const headers = {};
  if (req.headers.range) {
    headers["Range"] = req.headers.range;
  }
  headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36";

  let activeReq = null;
  let activeRes = null;

  req.on("close", () => {
    if (activeReq && !activeReq.destroyed) {
      activeReq.destroy();
    }
    if (activeRes && !activeRes.destroyed) {
      activeRes.destroy();
    }
  });

  function makeRequest(url) {
    if (req.destroyed) return;
    const parsed = new URL(url);
    const client = parsed.protocol === "https:" ? https : http;
    activeReq = client.get(url, { headers }, (upstreamRes) => {
      activeRes = upstreamRes;
      if (upstreamRes.statusCode >= 300 && upstreamRes.statusCode < 400 && upstreamRes.headers.location) {
        return makeRequest(upstreamRes.headers.location);
      }

      const fHeaders = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Accept-Ranges": "bytes",
        "Content-Type": upstreamRes.headers["content-type"] || "video/mp4",
      };
      if (upstreamRes.headers["content-length"]) fHeaders["Content-Length"] = upstreamRes.headers["content-length"];
      if (upstreamRes.headers["content-range"]) fHeaders["Content-Range"] = upstreamRes.headers["content-range"];
      if (upstreamRes.headers["content-disposition"]) fHeaders["Content-Disposition"] = upstreamRes.headers["content-disposition"];

      res.writeHead(upstreamRes.statusCode, fHeaders);
      upstreamRes.pipe(res);
    });

    activeReq.on("error", (err) => {
      if (!res.headersSent && !req.destroyed) {
        res.status(502).json({ error: err.message });
      }
    });
  }

  makeRequest(getTargetUrl());
}

module.exports = {
  GDriveManager,
  normalizeTitleKey,
  streamLocalFile,
  streamGDriveProxy
};
