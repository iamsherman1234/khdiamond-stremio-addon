#!/usr/bin/env python3
"""
web_ui.py — KhDiamond Multi-User Addon Server
Port: 7003

Routes:
  GET  /                        → upload page
  POST /upload                  → receive cookies, generate token, trigger pipeline
  GET  /status/{token}          → show status page
  GET  /refresh/{token}         → re-upload cookies page
  POST /refresh/{token}         → receive new cookies, re-trigger pipeline

  GET  /u/{token}/manifest.json → per-user Stremio manifest
  GET  /u/{token}/catalog/{type}/{id}.json
  GET  /u/{token}/meta/{type}/{id}.json
  GET  /u/{token}/stream/{type}/{id}.json
"""

import os
import uuid
import json
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from http.cookiejar import MozillaCookieJar

from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import uvicorn

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR      = Path("/root/khdiamond")
USERS_DIR     = BASE_DIR / "users"
ADDON_BASE    = os.environ.get("ADDON_URL", "https://sudolocal.qzz.io")
MF_PRIMARY    = os.environ.get("MEDIAFLOW_URL",  "https://sudolocal.qzz.io/mediaflow-py")
MF_FALLBACK   = os.environ.get("MEDIAFLOW_URL2", "https://mediaflow-proxy-l98z.onrender.com")
MF_PASSWORD   = os.environ.get("MEDIAFLOW_PASSWORD", "")

CDN_URLS = [
    "https://media-1.khdmcloud.online/hls/{movie_id}/{quality}.m3u8",
    "https://khdiamondcdn.asia/hls/{movie_id}/{quality}.m3u8",
]

MF_SERVERS = [
    {"base": MF_PRIMARY,  "label": "S10"},
    {"base": MF_FALLBACK, "label": "Cloud"},
]

USERS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

# ── Helpers ───────────────────────────────────────────────────────────────────

def user_dir(token: str) -> Path:
    return USERS_DIR / token

def user_status(token: str) -> str:
    d = user_dir(token)
    if not d.exists():
        return "not_found"
    if (d / "error.txt").exists():
        return "error"
    if (d / "catalog.json").exists():
        return "ready"
    if (d / "running.txt").exists():
        return "pending"
    return "pending"

def validate_cookies(cookies_path: Path) -> bool:
    try:
        jar = MozillaCookieJar(str(cookies_path))
        jar.load(ignore_discard=True, ignore_expires=True)
        return len(list(jar)) > 0
    except Exception:
        return False

def load_catalog(token: str):
    cat_path = user_dir(token) / "catalog.json"
    if not cat_path.exists():
        return []
    try:
        return json.loads(cat_path.read_text())
    except Exception:
        return []

def make_proxy_url(mf_base: str, original_url: str) -> str:
    from urllib.parse import quote
    return (mf_base + "/proxy/hls/manifest.m3u8"
            + "?api_password=" + quote(MF_PASSWORD)
            + "&d=" + quote(original_url))

def build_streams(item: dict) -> list:
    streams = []
    title = item.get("title_khmer") or item.get("title_english", "")

    qualities = []
    if item.get("movie_id_4k"):
        qualities.append({"label": "4K (2160p)", "quality": "2160p",
                          "movie_id": item["movie_id_4k"], "name": "KhDiamond 4K"})
    qualities.append({"label": "1080p", "quality": "1080p",
                      "movie_id": item["movie_id"], "name": "KhDiamond"})
    qualities.append({"label": "720p",  "quality": "720p",
                      "movie_id": item["movie_id"], "name": "KhDiamond"})

    for q in qualities:
        for c, cdn in enumerate(CDN_URLS):
            cdn_label = "CDN1" if c == 0 else "CDN2"
            original_url = cdn.replace("{movie_id}", q["movie_id"]).replace("{quality}", q["quality"])
            for mf in MF_SERVERS:
                streams.append({
                    "url": make_proxy_url(mf["base"], original_url),
                    "name": q["name"],
                    "title": f"{q['label']} | {cdn_label} | {mf['label']}\n{title}",
                    "behaviorHints": {"notWebReady": False},
                })
    return streams

def run_pipeline(token: str):
    """Run scrape → resolve → sync in background for a user."""
    d = user_dir(token)
    running_file = d / "running.txt"
    error_file   = d / "error.txt"
    log_file     = d / "pipeline.log"
    cookies_path = d / "cookies.txt"

    running_file.write_text(datetime.now().isoformat())
    error_file.unlink(missing_ok=True)

    env = os.environ.copy()
    env["USER_TOKEN"]    = token
    env["USER_DIR"]      = str(d)
    env["COOKIES_PATH"]  = str(cookies_path)
    env["CATALOG_PATH"]  = str(d / "catalog.json")

    scripts = [
        ["python3", str(BASE_DIR / "user_scrape.py")],
        ["python3", str(BASE_DIR / "user_resolve.py")],
        ["python3", str(BASE_DIR / "user_sync.py")],
    ]

    try:
        with open(log_file, "w") as log:
            for script in scripts:
                log.write(f"\n=== {script[1]} ===\n")
                log.flush()
                result = subprocess.run(
                    script, env=env, capture_output=False,
                    stdout=log, stderr=log, timeout=600
                )
                if result.returncode != 0:
                    error_file.write_text(f"Failed: {script[1]}")
                    running_file.unlink(missing_ok=True)
                    return
    except Exception as e:
        error_file.write_text(str(e))
        running_file.unlink(missing_ok=True)
        return

    running_file.unlink(missing_ok=True)

# ── HTML Templates ────────────────────────────────────────────────────────────

def page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — KhDiamond</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #0f0f0f; color: #eee; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
    .card {{ background: #1a1a1a; border-radius: 16px; padding: 40px; max-width: 520px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
    h1 {{ font-size: 1.6rem; margin-bottom: 8px; color: #fff; }}
    .logo {{ font-size: 2rem; margin-bottom: 16px; }}
    p {{ color: #aaa; margin-bottom: 20px; line-height: 1.6; }}
    .upload-area {{ border: 2px dashed #333; border-radius: 12px; padding: 32px; text-align: center; margin-bottom: 20px; cursor: pointer; transition: border-color 0.2s; }}
    .upload-area:hover {{ border-color: #666; }}
    input[type=file] {{ display: none; }}
    .btn {{ background: #e8a000; color: #000; border: none; padding: 12px 28px; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; width: 100%; transition: background 0.2s; }}
    .btn:hover {{ background: #ffb800; }}
    .btn-secondary {{ background: #333; color: #eee; margin-top: 10px; }}
    .btn-secondary:hover {{ background: #444; }}
    .url-box {{ background: #111; border: 1px solid #333; border-radius: 8px; padding: 12px 16px; font-family: monospace; font-size: 0.85rem; word-break: break-all; color: #4af; margin-bottom: 16px; }}
    .status {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; margin-bottom: 16px; }}
    .status.ready {{ background: #1a3a1a; color: #4f4; }}
    .status.pending {{ background: #3a3a1a; color: #fa4; }}
    .status.error {{ background: #3a1a1a; color: #f44; }}
    .steps {{ list-style: none; margin-bottom: 24px; }}
    .steps li {{ padding: 8px 0; border-bottom: 1px solid #222; color: #aaa; font-size: 0.9rem; }}
    .steps li:last-child {{ border-bottom: none; }}
    .steps li span {{ color: #eee; }}
    a {{ color: #4af; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">💎</div>
    {body}
  </div>
</body>
</html>"""

UPLOAD_PAGE = page("Setup", """
  <h1>KhDiamond Addon</h1>
  <p>Upload your khdiamond.net cookies to get your personal Stremio addon URL.</p>
  <form action="/khdiamond-ui/upload" method="post" enctype="multipart/form-data" id="form">
    <div class="upload-area" onclick="document.getElementById('file').click()">
      <p style="margin:0">📁 Click to select <strong>cookies.txt</strong></p>
      <p style="margin:8px 0 0; font-size:0.8rem" id="fname">Netscape format (exported from browser)</p>
    </div>
    <input type="file" id="file" name="cookies" accept=".txt" onchange="document.getElementById('fname').textContent=this.files[0].name">
    <button type="submit" class="btn">Get My Addon URL</button>
  </form>
  <p style="margin-top:16px; font-size:0.8rem">
    Need help exporting cookies? Use the 
    <a href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank">Get cookies.txt</a> 
    Chrome extension on khdiamond.net.
  </p>
""")

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return UPLOAD_PAGE

@app.post("/upload", response_class=HTMLResponse)
async def upload(cookies: UploadFile = File(...)):
    content = await cookies.read()

    # Generate token + save cookies
    token = str(uuid.uuid4())[:8]
    d = user_dir(token)
    d.mkdir(parents=True, exist_ok=True)
    cookies_path = d / "cookies.txt"
    cookies_path.write_bytes(content)

    # Validate cookies format
    if not validate_cookies(cookies_path):
        cookies_path.unlink(missing_ok=True)
        d.rmdir()
        return HTMLResponse(page("Error", """
          <h1>Invalid Cookies</h1>
          <p>The file doesn't appear to be a valid Netscape cookies file. Please export again from your browser.</p>
          <a href="/khdiamond-ui/"><button class="btn btn-secondary">Try Again</button></a>
        """))

    # Save metadata
    (d / "meta.json").write_text(json.dumps({
        "token": token,
        "created": datetime.now().isoformat(),
        "filename": cookies.filename,
    }))

    # Run pipeline in background
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()

    return RedirectResponse(f"/khdiamond-ui/status/{token}", status_code=303)

@app.get("/status/{token}", response_class=HTMLResponse)
async def status(token: str):
    st = user_status(token)
    addon_url = f"{ADDON_BASE}/khdiamond-ui/u/{token}/manifest.json"

    # Check expired before other statuses
    if (user_dir(token) / "expired.txt").exists():
        return HTMLResponse(page("Cookies Expired", f"""
          <h1>Cookies Expired</h1>
          <span class="status error">⚠ Cookies Expired</span>
          <p>Your khdiamond.net cookies have expired. Please export fresh cookies from your browser and re-upload.</p>
          <a href="/khdiamond-ui/refresh/{token}"><button class="btn">Re-upload Cookies</button></a>
          <p style="margin-top:16px; font-size:0.8rem; color:#666">Token: {token}</p>
        """))

    if st == "not_found":
        return HTMLResponse(page("Not Found", """
          <h1>Not Found</h1>
          <p>This addon token doesn't exist.</p>
          <a href="/khdiamond-ui/"><button class="btn">Create New Addon</button></a>
        """))

    if st == "pending":
        return HTMLResponse(page("Building...", f"""
          <h1>Building Your Catalog</h1>
          <span class="status pending">⏳ Processing</span>
          <p>We're scraping your purchases and resolving stream IDs. This takes about <strong>3–5 minutes</strong>.</p>
          <ul class="steps">
            <li>✅ <span>Cookies uploaded</span></li>
            <li>⏳ <span>Scraping purchases...</span></li>
            <li>⏳ <span>Resolving stream IDs...</span></li>
            <li>⏳ <span>Fetching metadata...</span></li>
          </ul>
          <p>This page will update automatically.</p>
          <meta http-equiv="refresh" content="15">
          <div class="url-box">Your addon URL (save this):<br>{addon_url}</div>
        """))

    if st == "error":
        error = (user_dir(token) / "error.txt").read_text()
        return HTMLResponse(page("Error", f"""
          <h1>Pipeline Error</h1>
          <span class="status error">❌ Failed</span>
          <p>{error}</p>
          <p>This is usually caused by expired cookies. Please re-upload.</p>
          <a href="/khdiamond-ui/refresh/{token}"><button class="btn">Re-upload Cookies</button></a>
        """))

    # Ready
    catalog = load_catalog(token)
    return HTMLResponse(page("Ready!", f"""
      <h1>Your Addon is Ready!</h1>
      <span class="status ready">✅ {len(catalog)} movies/episodes</span>
      <p>Install this URL in Stremio:</p>
      <div class="url-box">{addon_url}</div>
      <button class="btn" onclick="navigator.clipboard.writeText('{addon_url}')">Copy URL</button>
      <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Re-upload Cookies</button></a>
      <p style="margin-top:16px; font-size:0.8rem; color:#666">Token: {token} — bookmark this page to manage your addon.</p>
    """))

@app.get("/refresh/{token}", response_class=HTMLResponse)
async def refresh_page(token: str):
    if user_status(token) == "not_found":
        return RedirectResponse("/khdiamond-ui/")
    return HTMLResponse(page("Refresh", f"""
      <h1>Re-upload Cookies</h1>
      <p>Your cookies may have expired. Upload a fresh <strong>cookies.txt</strong> to refresh your catalog.</p>
      <form action="/khdiamond-ui/refresh/{token}" method="post" enctype="multipart/form-data">
        <div class="upload-area" onclick="document.getElementById('file2').click()">
          <p style="margin:0">📁 Click to select <strong>cookies.txt</strong></p>
        </div>
        <input type="file" id="file2" name="cookies" accept=".txt">
        <button type="submit" class="btn">Refresh My Catalog</button>
      </form>
    """))

@app.post("/refresh/{token}", response_class=HTMLResponse)
async def refresh_upload(token: str, cookies: UploadFile = File(...)):
    if user_status(token) == "not_found":
        return RedirectResponse("/khdiamond-ui/")
    content = await cookies.read()
    d = user_dir(token)
    cookies_path = d / "cookies.txt"
    cookies_path.write_bytes(content)

    if not validate_cookies(cookies_path):
        return HTMLResponse(page("Error", f"""
          <h1>Invalid Cookies</h1>
          <p>Please export again from your browser.</p>
          <a href="/khdiamond-ui/refresh/{token}"><button class="btn btn-secondary">Try Again</button></a>
        """))

    # Clear old catalog + error, re-run pipeline
    (d / "catalog.json").unlink(missing_ok=True)
    (d / "error.txt").unlink(missing_ok=True)
    (d / "expired.txt").unlink(missing_ok=True)
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()
    return RedirectResponse(f"/khdiamond-ui/status/{token}", status_code=303)

# ── Stremio API (per-user) ────────────────────────────────────────────────────

def make_manifest(token: str) -> dict:
    return {
        "id": f"com.khdiamond.user.{token}",
        "version": "1.0.0",
        "name": f"KhDiamond ({token})",
        "description": "Your personal Khmer dubbed movie library.",
        "logo": "https://khdiamond.net/wp-content/uploads/2025/02/khdiamond-logo.png",
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series"],
        "idPrefixes": [f"khd_{token}_"],
        "catalogs": [
            {"type": "movie",  "id": f"khdiamond_movies_{token}",  "name": "KhDiamond Movies",  "extra": [{"name": "search", "isRequired": False}]},
            {"type": "series", "id": f"khdiamond_series_{token}", "name": "KhDiamond Series", "extra": [{"name": "search", "isRequired": False}]},
        ],
        "behaviorHints": {"adult": False, "p2p": False},
    }

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Content-Type": "application/json; charset=utf-8",
}

@app.get("/u/{token}/manifest.json")
async def user_manifest(token: str):
    if user_status(token) == "not_found":
        return JSONResponse({"error": "not found"}, status_code=404, headers=CORS_HEADERS)
    return JSONResponse(make_manifest(token), headers=CORS_HEADERS)

@app.get("/u/{token}/catalog/{type}/{id}.json")
async def user_catalog(token: str, type: str, id: str, request: Request):
    catalog = load_catalog(token)
    search = request.query_params.get("search", "").lower().strip()
    items = [m for m in catalog if m.get("type") == type]
    if search:
        items = [m for m in items if
                 search in (m.get("title_english") or "").lower() or
                 search in (m.get("title_khmer") or "").lower()]
    prefix = f"khd_{token}_"
    metas = [{
        "id": prefix + m["khd_id"].replace("khd_", ""),
        "type": m["type"],
        "name": m.get("title_english", ""),
        "poster": m.get("poster", ""),
        "background": m.get("backdrop", ""),
        "description": m.get("overview", ""),
        "year": m.get("year", ""),
        "genres": m.get("genres", []),
    } for m in items]
    return JSONResponse({"metas": metas}, headers=CORS_HEADERS)

@app.get("/u/{token}/meta/{type}/{id}.json")
async def user_meta(token: str, type: str, id: str):
    prefix = f"khd_{token}_"
    if not id.startswith(prefix):
        return JSONResponse({"meta": None}, headers=CORS_HEADERS)
    real_id = "khd_" + id[len(prefix):]
    catalog = load_catalog(token)
    item = next((m for m in catalog if m.get("khd_id") == real_id), None)
    if not item:
        return JSONResponse({"meta": None}, headers=CORS_HEADERS)
    desc = (item.get("title_khmer", "") + "\n\n" if item.get("title_khmer") else "") + item.get("overview", "")
    return JSONResponse({"meta": {
        "id": id, "type": item["type"],
        "name": item.get("title_english", ""),
        "poster": item.get("poster", ""),
        "background": item.get("backdrop", ""),
        "description": desc.strip(),
        "year": item.get("year", ""),
        "genres": item.get("genres", []),
    }}, headers=CORS_HEADERS)

@app.get("/u/{token}/stream/{type}/{id}.json")
async def user_stream(token: str, type: str, id: str):
    prefix = f"khd_{token}_"
    if not id.startswith(prefix):
        return JSONResponse({"streams": []}, headers=CORS_HEADERS)
    real_id = "khd_" + id[len(prefix):]
    catalog = load_catalog(token)
    item = next((m for m in catalog if m.get("khd_id") == real_id), None)
    if not item or not item.get("movie_id"):
        return JSONResponse({"streams": []}, headers=CORS_HEADERS)
    return JSONResponse({"streams": build_streams(item)}, headers=CORS_HEADERS)

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7003, root_path="/khdiamond-ui")
