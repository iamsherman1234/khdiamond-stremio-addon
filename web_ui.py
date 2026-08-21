#!/usr/bin/env python3
"""
web_ui.py — KhDiamond Multi-User Addon Server
For subdomain: khdiamond-ui.sudolocal.qzz.io
"""

import os
import re
import uuid
import json
import subprocess
import threading
from urllib.parse import parse_qs
from pathlib import Path
from datetime import datetime
from http.cookiejar import MozillaCookieJar

from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import uvicorn
from khdiamond_credentials import (delete_credentials,
                                    login_khdiamond as credential_login,
                                    save_credentials)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("KH_DIAMOND_BASE_DIR", "/root/khdiamond"))
USERS_DIR = BASE_DIR / "users"
FULL_CATALOG_PATH = Path(os.environ.get("FULL_CATALOG_PATH", str(BASE_DIR / "full_catalog.json")))
ADDON_BASE = os.environ.get("KH_DIAMOND_UI_BASE", "https://khdiamond-ui.sudolocal.qzz.io").rstrip("/")

USERS_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI()

# Strong CORS for Stremio
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Content-Type": "application/json; charset=utf-8",
}
IMDB_ID_RE = re.compile(r"^tt\d{7,10}$")
CATALOG_PAGE_SIZE = int(os.environ.get("KH_DIAMOND_CATALOG_PAGE_SIZE", "100"))

def usable_poster_url(value: str) -> str:
    value = str(value or "").strip()
    lowered = value.lower().split("?", 1)[0]
    if not value.startswith(("http://", "https://")):
        return ""
    if "/themes/dooplay/assets/img/" in lowered:
        return ""
    return value

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

def save_cookies(d: Path, content: bytes) -> Path:
    cookies_path = d / "cookies.txt"
    cookies_path.write_bytes(content)
    return cookies_path

def load_catalog(token: str):
    cat_path = user_dir(token) / "catalog.json"
    if not cat_path.exists():
        return []
    try:
        catalog = json.loads(cat_path.read_text())
        return catalog if isinstance(catalog, list) else []
    except Exception:
        return []

def load_full_catalog():
    if not FULL_CATALOG_PATH.exists():
        return []
    try:
        catalog = json.loads(FULL_CATALOG_PATH.read_text())
        return catalog if isinstance(catalog, list) else []
    except Exception:
        return []

def normalize_imdb_id(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return value if value.startswith("tt") else "tt" + value.removeprefix("tt")

def verified_imdb_id(value: str) -> str:
    value = normalize_imdb_id(value)
    return value if IMDB_ID_RE.fullmatch(value) else ""

def item_matches_id(item: dict, token: str, id: str) -> bool:
    prefix = f"khd_{token}_"
    if id.startswith(prefix):
        return item.get("khd_id") == "khd_" + id[len(prefix):]
    if id.startswith("tt"):
        return normalize_imdb_id(item.get("imdb_id")) == id
    return False

def split_video_id(value: str):
    """Return (base id, season, episode); movie IDs have no season/episode."""
    parts = str(value or "").rsplit(":", 2)
    if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
        return parts[0], int(parts[1]), int(parts[2])
    return str(value or ""), None, None

def public_item_id(item: dict) -> str:
    imdb_id = verified_imdb_id(item.get("imdb_id"))
    if imdb_id:
        return imdb_id
    slug = str(item.get("slug") or "").strip()
    return f"khdcat_{slug}" if slug else str(item.get("khd_id") or "")

def full_item_matches_id(item: dict, value: str) -> bool:
    base_id, _, _ = split_video_id(value)
    if base_id.startswith("tt"):
        return verified_imdb_id(item.get("imdb_id")) == base_id
    if base_id.startswith("khdcat_"):
        return item.get("slug") == base_id[len("khdcat_"):]
    return item.get("khd_id") == base_id

def find_full_item(catalog: list, media_type: str, value: str):
    return next((item for item in catalog
                 if item.get("type") == media_type and full_item_matches_id(item, value)), None)

def find_full_items(catalog: list, media_type: str, value: str) -> list:
    return [item for item in catalog
            if item.get("type") == media_type and full_item_matches_id(item, value)]

def same_site_item(left: dict, right: dict) -> bool:
    left_slug = str(left.get("slug") or "")
    right_slug = str(right.get("slug") or "")
    left_url = normalized_page_url(left.get("page_url"))
    right_url = normalized_page_url(right.get("page_url"))
    return bool((left_slug and left_slug == right_slug)
                or (left_url and left_url == right_url))

def episode_matches_personal(episode: dict, personal_item: dict) -> bool:
    episode_url = normalized_page_url(episode.get("page_url"))
    episode_slug = episode.get("slug") or episode_url.rstrip("/").rsplit("/", 1)[-1]
    personal_url = normalized_page_url(personal_item.get("page_url"))
    personal_slug = str(personal_item.get("slug") or "")
    return bool((episode_slug and episode_slug == personal_slug)
                or (episode_url and episode_url == personal_url))

def purchased_series_episodes(full_item: dict, personal: list) -> list:
    personal_series = [item for item in personal if item.get("type") == "series"]
    episodes = []
    for episode in full_item.get("episodes", []) or []:
        if any(episode_matches_personal(episode, item) for item in personal_series):
            episodes.append(episode)
    return episodes

def extract_ep_season_num(ep: dict) -> tuple[int, int]:
    s = ep.get("season")
    e = ep.get("episode")
    if s is not None and e is not None and str(s).isdigit() and str(e).isdigit():
        return int(s), int(e)
    slug = str(ep.get("slug") or "")
    m = re.search(r"(\d+)x(\d+)", slug)
    if m:
        return int(m.group(1)), int(m.group(2))
    title = str(ep.get("title") or ep.get("title_khmer") or ep.get("title_english") or "")
    m2 = re.search(r"S(\d+)\s*E(\d+)", title, re.IGNORECASE)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    return int(s or 1), int(e or 1)

def purchased_catalog_items(token: str, media_type: str, full_catalog: list, personal: list) -> list:
    if media_type == "movie":
        items = []
        for personal_item in personal:
            if personal_item.get("type") != "movie":
                continue
            full_item = next((item for item in full_catalog
                              if item.get("type") == "movie" and same_site_item(item, personal_item)), None)
            if full_item:
                items.append(full_item)
            else:
                fallback = personal_item.copy()
                fallback["_fallback_id"] = (normalize_imdb_id(fallback.get("imdb_id"))
                                           or f"khd_{token}_" + fallback.get("khd_id", "").removeprefix("khd_"))
                items.append(fallback)
        return items

    if media_type == "series":
        personal_series = [item for item in personal if item.get("type") == "series"]
        series_by_slug = {}
        for ep in personal_series:
            s_slug = ep.get("series") or (ep.get("slug", "").rsplit("-", 1)[0] if "-" in ep.get("slug", "") else ep.get("slug", ""))
            series_by_slug.setdefault(s_slug, []).append(ep)

        items = []
        for s_slug, ep_list in series_by_slug.items():
            full_item = next((item for item in full_catalog
                              if item.get("type") == "series"
                              and (item.get("slug") == s_slug or any(same_site_item(item, ep) for ep in ep_list))), None)
            if full_item:
                matched_eps = purchased_series_episodes(full_item, personal)
                matched_keys = {(episode_number(ep.get("season")), episode_number(ep.get("episode"))) for ep in matched_eps}
                episodes = list(matched_eps)
                for ep in ep_list:
                    s_num, ep_num = extract_ep_season_num(ep)
                    if (s_num, ep_num) not in matched_keys:
                        matched_keys.add((s_num, ep_num))
                        episodes.append({
                            "season": s_num,
                            "episode": ep_num,
                            "title": ep.get("title_english") or ep.get("title_khmer") or f"Episode {ep_num}",
                            "page_url": ep.get("page_url", ""),
                            "slug": ep.get("slug", ""),
                            "thumbnail": ep.get("poster", ""),
                        })
                episodes.sort(key=lambda x: (episode_number(x.get("season")), episode_number(x.get("episode"))))
                item = full_item.copy()
                item["episodes"] = episodes
                items.append(item)
            else:
                first_ep = ep_list[0]
                series_title_khmer = first_ep.get("title_khmer", "")
                series_title_khmer = re.sub(r"\s*[\u2013\u2014\-]\s*S\d+E\d+.*$", "", series_title_khmer).strip()
                series_title_english = first_ep.get("title_english", "")
                series_title_english = re.sub(r"\s*[\u2013\u2014\-]\s*S\d+E\d+.*$", "", series_title_english).strip()

                episodes = []
                for ep in sorted(ep_list, key=lambda x: extract_ep_season_num(x)):
                    s_num, ep_num = extract_ep_season_num(ep)
                    episodes.append({
                        "season": s_num,
                        "episode": ep_num,
                        "title": ep.get("title_english") or ep.get("title_khmer") or f"Episode {ep_num}",
                        "page_url": ep.get("page_url", ""),
                        "slug": ep.get("slug", ""),
                        "thumbnail": ep.get("poster", ""),
                    })

                fallback = {
                    "type": "series",
                    "slug": s_slug,
                    "khd_id": f"khdcat_{s_slug}",
                    "_fallback_id": normalize_imdb_id(first_ep.get("imdb_id")) or f"khd_{token}_{s_slug}",
                    "imdb_id": first_ep.get("imdb_id", ""),
                    "tmdb_id": first_ep.get("tmdb_id", ""),
                    "title_khmer": series_title_khmer,
                    "title_english": series_title_english or series_title_khmer,
                    "year": first_ep.get("year", ""),
                    "poster": first_ep.get("poster", ""),
                    "backdrop": first_ep.get("backdrop", ""),
                    "genres": first_ep.get("genres", []),
                    "overview": first_ep.get("overview", ""),
                    "imdb_rating": first_ep.get("imdb_rating", ""),
                    "episodes": episodes,
                }
                items.append(fallback)
        return items

    return []

def episode_videos(item: dict) -> list:
    base_id = public_item_id(item)
    videos = []
    for ep in item.get("episodes", []) or []:
        try:
            season = int(ep.get("season") or 1)
            episode = int(ep.get("episode") or 1)
        except (TypeError, ValueError):
            continue
        video = {
            "id": f"{base_id}:{season}:{episode}",
            "title": ep.get("title") or f"Episode {episode}",
            "season": season,
            "episode": episode,
        }
        if ep.get("thumbnail"):
            video["thumbnail"] = ep["thumbnail"]
        released = str(ep.get("released") or "")
        if released and len(released) >= 10 and released[4:5] == "-":
            video["released"] = released
        videos.append(video)
    return videos

def stremio_meta(item: dict, include_videos: bool = False) -> dict:
    description = item.get("overview") or item.get("overview_en") or ""
    khmer_title = item.get("title_khmer") or ""
    english_title = item.get("title_english") or item.get("original_title") or ""
    if khmer_title and english_title and khmer_title != english_title:
        description = f"{khmer_title}\n\n{description}".strip()
    meta = {
        "id": public_item_id(item),
        "type": item.get("type", "movie"),
        "name": english_title or khmer_title,
        "poster": usable_poster_url(item.get("poster")) or usable_poster_url(item.get("tmdb_poster")),
        "background": item.get("backdrop") or "",
        "description": description,
        "year": item.get("year") or "",
        "imdbRating": item.get("imdb_rating") or "",
        "genres": item.get("genres") or [],
    }
    if include_videos and item.get("type") == "series":
        meta["videos"] = episode_videos(item)
    return meta

def normalized_page_url(value: str) -> str:
    return str(value or "").rstrip("/")

def episode_number(value, default: int = 1):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default

def find_purchased_item(personal: list, full_item: dict, requested_id: str):
    """Map a public catalog ID to an owned movie/episode without trusting stale IDs."""
    _, season, episode = split_video_id(requested_id)
    if full_item.get("type") == "series":
        if season is None or episode is None:
            return None
        full_slug = full_item.get("slug", "")
        full_episode = next((ep for ep in full_item.get("episodes", []) or []
                             if episode_number(ep.get("season")) == season
                             and episode_number(ep.get("episode")) == episode), None)
        if full_episode:
            episode_slug = full_episode.get("page_url", "").rstrip("/").rsplit("/", 1)[-1]
            episode_slug = full_episode.get("slug") or episode_slug
            episode_url = normalized_page_url(full_episode.get("page_url"))
            matched = next((item for item in personal
                            if item.get("type") == "series"
                            and ((episode_slug and item.get("slug") == episode_slug)
                                 or (episode_url and normalized_page_url(item.get("page_url")) == episode_url))), None)
            if matched:
                return matched

        return next((item for item in personal
                     if item.get("type") == "series"
                     and episode_number(item.get("season")) == season
                     and episode_number(item.get("episode")) == episode
                     and (not full_slug or item.get("series") == full_slug or full_slug in str(item.get("slug", "")))), None)

    slug = full_item.get("slug") or ""
    page_url = normalized_page_url(full_item.get("page_url"))
    return next((item for item in personal
                 if item.get("type") == "movie"
                 and ((slug and item.get("slug") == slug)
                      or (page_url and normalized_page_url(item.get("page_url")) == page_url))), None)

def make_proxy_url(mf_base: str, original_url: str) -> str:
    MF_PASSWORD = os.environ.get("MEDIAFLOW_PASSWORD", "")
    if not MF_PASSWORD:
        return original_url
    from urllib.parse import quote
    return (mf_base + "/proxy/hls/manifest.m3u8"
            + "?api_password=" + quote(MF_PASSWORD)
            + "&d=" + quote(original_url))

def build_streams(item: dict) -> list:
    streams = []
    title = item.get("title_khmer") or item.get("title_english", "")
    cdn_urls = [
        "https://media-1.khdmcloud.online/hls/{movie_id}/{quality}.m3u8",
        "https://khdm-media.tripplestream.online/hls/{movie_id}/{quality}.m3u8",
    ]
    mf_servers = [
        {"base": os.environ.get("MEDIAFLOW_URL", "https://sudolocal.qzz.io/mediaflow-py"), "label": "S10+"},
        {"base": os.environ.get("MEDIAFLOW_URL2", "https://mediaflow-proxy-l98z.onrender.com"), "label": "Cloud"},
    ]

    qualities = []
    if item.get("movie_id_4k"):
        qualities.append({"label": "4K (2160p)", "quality": "2160p", "movie_id": item["movie_id_4k"], "name": "KhDiamond 4K"})
    qualities.append({"label": "1080p", "quality": "1080p", "movie_id": item["movie_id"], "name": "KhDiamond"})
    qualities.append({"label": "720p", "quality": "720p", "movie_id": item["movie_id"], "name": "KhDiamond"})

    for q in qualities:
        if not q.get("movie_id"):
            continue
        for c, cdn in enumerate(cdn_urls):
            cdn_label = f"CDN{c + 1}"
            original_url = cdn.replace("{movie_id}", q["movie_id"]).replace("{quality}", q["quality"])
            for mf in mf_servers:
                url = make_proxy_url(mf["base"], original_url)
                if not url:
                    continue
                streams.append({
                    "url": url,
                    "name": q["name"],
                    "title": f"{q['label']} | {cdn_label} | {mf['label']}\n{title}",
                    "behaviorHints": {"notWebReady": False},
                })
    return streams

def run_pipeline(token: str):
    d = user_dir(token)
    running_file = d / "running.txt"
    error_file = d / "error.txt"
    log_file = d / "pipeline.log"
    cookies_path = d / "cookies.txt"

    running_file.write_text(datetime.now().isoformat())
    error_file.unlink(missing_ok=True)

    env = os.environ.copy()
    env["USER_TOKEN"] = token
    env["USER_DIR"] = str(d)
    env["COOKIES_PATH"] = str(cookies_path)
    env["CATALOG_PATH"] = str(d / "catalog.json")

    scripts = [
        ["python3", str(BASE_DIR / "user_scrape.py")],
        ["python3", str(BASE_DIR / "user_resolve.py")],
        ["python3", str(BASE_DIR / "user_sync.py")],
    ]

    try:
        with open(log_file, "w") as log:
            for script in scripts:
                log.write(f"\n=== Running {script[1]} ===\n")
                result = subprocess.run(script, env=env, stdout=log, stderr=log, timeout=600)
                if result.returncode != 0:
                    error_file.write_text(f"Failed at {script[1]}")
                    running_file.unlink(missing_ok=True)
                    return
    except Exception as e:
        error_file.write_text(str(e))
        running_file.unlink(missing_ok=True)
        return

    running_file.unlink(missing_ok=True)

# ── HTML Template ─────────────────────────────────────────────────────────────
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
    .card {{ background: #1a1a1a; border-radius: 16px; padding: 40px; max-width: 560px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
    h1 {{ font-size: 1.6rem; margin-bottom: 8px; color: #fff; }}
    .logo {{ font-size: 2.4rem; margin-bottom: 16px; }}
    .tabs {{ display: flex; gap: 8px; margin-bottom: 20px; background: #111; padding: 4px; border-radius: 10px; }}
    .tab {{ flex: 1; padding: 12px; border-radius: 8px; background: #1a1a1a; color: #aaa; cursor: pointer; text-align: center; font-weight: 500; }}
    .tab.active {{ background: #e8a000; color: #000; font-weight: 600; }}
    .upload-area {{ border: 2px dashed #444; border-radius: 12px; padding: 32px; text-align: center; margin-bottom: 16px; cursor: pointer; }}
    .upload-area:hover {{ border-color: #e8a000; }}
    textarea {{ width: 100%; height: 170px; background: #111; border: 1px solid #333; border-radius: 8px; color: #eee; padding: 14px; font-family: monospace; resize: vertical; }}
    .btn {{ background: #e8a000; color: #000; border: none; padding: 14px; border-radius: 8px; font-size: 1.05rem; font-weight: 600; cursor: pointer; width: 100%; margin-top: 10px; }}
    .btn:hover {{ background: #ffb800; }}
    .url-box {{ background: #111; border: 1px solid #333; border-radius: 8px; padding: 14px; word-break: break-all; color: #4af; margin: 16px 0; }}
    .status {{ padding: 6px 16px; border-radius: 20px; font-weight: 600; }}
    .status.ready {{ background: #1a3a1a; color: #4f4; }}
    .status.pending {{ background: #3a3a1a; color: #fa4; }}
    .status.error {{ background: #3a1a1a; color: #f44; }}
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

# ── Upload Page ───────────────────────────────────────────────────────────────
UPLOAD_PAGE = page("KhDiamond Setup", """
  <h1>KhDiamond Addon</h1>
  <p>Provide your khdiamond.net credentials to get your personal Stremio addon.</p>
  <div class="tabs">
    <div class="tab active" onclick="switchTab(0)">🔑 Login</div>
    <div class="tab" onclick="switchTab(1)">📋 Paste Cookies</div>
    <div class="tab" onclick="switchTab(2)">📁 Upload File</div>
  </div>
  <div id="tab0">
    <form action="/upload" method="post">
      <input type="hidden" name="method" value="login">
      <input type="text" name="username" placeholder="Email / Username / Phone" required style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
      <input type="password" name="password" placeholder="Password" required style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
      <button type="submit" class="btn">Login & Get Addon URL</button>
    </form>
  </div>
  <div id="tab1" style="display:none">
    <form action="/upload" method="post">
      <input type="hidden" name="method" value="paste">
      <textarea name="cookies_text" placeholder="Paste your full cookies.txt content here..."></textarea>
      <button type="submit" class="btn">Get My Addon URL</button>
    </form>
  </div>
  <div id="tab2" style="display:none">
    <form action="/upload" method="post" enctype="multipart/form-data">
      <input type="hidden" name="method" value="file">
      <div class="upload-area" onclick="document.getElementById('file').click()">
        <p style="margin:0">📁 Click to select <strong>cookies.txt</strong></p>
        <p style="margin:8px 0 0; font-size:0.8rem" id="fname">Netscape format</p>
      </div>
      <input type="file" id="file" name="cookies" accept=".txt" onchange="document.getElementById('fname').textContent=this.files[0]?.name||'No file chosen'">
      <button type="submit" class="btn">Get My Addon URL</button>
    </form>
  </div>
  <p style="margin-top:18px; font-size:0.8rem">Need help? Use the <a href="https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank">Get cookies.txt LOCALLY</a> extension.</p>
  <script>
    function switchTab(n) {
      [0,1,2].forEach(i => document.getElementById('tab'+i).style.display = i===n ? 'block' : 'none');
      document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', i === n));
    }
  </script>
""")
# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return UPLOAD_PAGE

@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    cookies: UploadFile = File(None),
    cookies_text: str = Form(None),
    method: str = Form("login"),
    username: str = Form(None),
    password: str = Form(None),
):
    token = str(uuid.uuid4())[:8]
    d = user_dir(token)
    d.mkdir(parents=True, exist_ok=True)
    cookies_path = d / "cookies.txt"

    if method == "login":
        u = (username or "").strip()
        p = (password or "").strip()
        if not u or not p:
            d.rmdir()
            return HTMLResponse(page("Error", "<h1>Missing Credentials</h1><a href='/'><button class='btn btn-secondary'>Try Again</button></a>"))
        ok, msg = credential_login(u, p, cookies_path)
        if not ok:
            cookies_path.unlink(missing_ok=True)
            d.rmdir()
            return HTMLResponse(page("Login Failed", f"<h1>Login Failed</h1><p>{msg}</p><a href='/'><button class='btn btn-secondary'>Try Again</button></a>"))
        save_credentials(d, u, p)
    elif method == "paste" and cookies_text and cookies_text.strip():
        cookies_path.write_bytes(cookies_text.strip().encode("utf-8"))
        if not validate_cookies(cookies_path):
            cookies_path.unlink(missing_ok=True)
            d.rmdir()
            return HTMLResponse(page("Error", "<h1>Invalid Cookies</h1><a href='/'><button class='btn btn-secondary'>Try Again</button></a>"))
    elif method == "file" and cookies and cookies.filename:
        cookies_path.write_bytes(await cookies.read())
        if not validate_cookies(cookies_path):
            cookies_path.unlink(missing_ok=True)
            d.rmdir()
            return HTMLResponse(page("Error", "<h1>Invalid Cookies</h1><a href='/'><button class='btn btn-secondary'>Try Again</button></a>"))
    else:
        d.rmdir()
        return HTMLResponse(page("Error", "<h1>No Credentials Provided</h1><a href='/'><button class='btn btn-secondary'>Try Again</button></a>"))

    (d / "meta.json").write_text(json.dumps({
        "token": token,
        "created": datetime.now().isoformat(),
        "source": method,
    }, indent=2))
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()
    return RedirectResponse(f"/status/{token}", status_code=303)


@app.get("/status/{token}", response_class=HTMLResponse)
async def status(token: str):
    # (Full status logic - same as before)
    st = user_status(token)
    addon_url = f"{ADDON_BASE}/u/{token}/manifest.json"

    if (user_dir(token) / "expired.txt").exists():
        return HTMLResponse(page("Cookies Expired", f"""
          <h1>Cookies Expired</h1>
          <span class="status error">Cookies Expired</span>
          <p>Automatic login failed. Log in again or provide fresh cookies.</p>
          <a href="/refresh/{token}"><button class="btn">Renew Session</button></a>
        """))

    if st == "not_found":
        return HTMLResponse(page("Not Found", "<h1>Not Found</h1><a href='/'><button class='btn'>Create New</button></a>"))

    if st == "pending":
        return HTMLResponse(page("Processing", f"""
          <h1>Building Catalog...</h1>
          <span class="status pending">⏳ Processing</span>
          <meta http-equiv="refresh" content="12">
          <div class="url-box">{addon_url}</div>
        """))

    if st == "error":
        return HTMLResponse(page("Error", "<h1>Error Occurred</h1><a href='/refresh/{token}'><button class='btn'>Re-upload Cookies</button></a>".format(token=token)))

    catalog = load_catalog(token)
    return HTMLResponse(page("Ready", f"""
      <h1>✅ Your Addon is Ready!</h1>
      <span class="status ready">{len(catalog)} items</span>
      <div class="url-box">{addon_url}</div>
      <button class="btn" onclick="navigator.clipboard.writeText('{addon_url}')">Copy URL</button>
      <a href="/refresh/{token}"><button class="btn btn-secondary">Re-upload Cookies</button></a>
    """))


@app.get("/refresh/{token}", response_class=HTMLResponse)
async def refresh_page(token: str):
    if user_status(token) == "not_found":
        return RedirectResponse("/")
    return HTMLResponse(page("Refresh", f"""
      <h1>Renew KhDiamond Session</h1>
      <div class="tabs">
        <div class="tab active" onclick="switchTab(0)">🔑 Login</div>
        <div class="tab" onclick="switchTab(1)">📋 Paste</div>
        <div class="tab" onclick="switchTab(2)">📁 File</div>
      </div>
      <div id="tab0">
        <form action="/refresh/{token}" method="post">
          <input type="hidden" name="method" value="login">
          <input type="text" name="username" placeholder="Email / Username / Phone" required style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
          <input type="password" name="password" placeholder="Password" required style="width:100%;background:#111;border:1px solid #333;border-radius:8px;color:#eee;padding:12px;font-size:0.95rem;margin-bottom:12px;display:block">
          <button type="submit" class="btn">Login, Save & Refresh</button>
        </form>
      </div>
      <div id="tab1" style="display:none">
        <form action="/refresh/{token}" method="post">
          <input type="hidden" name="method" value="paste">
          <textarea name="cookies_text" placeholder="Paste new cookies..."></textarea>
          <button type="submit" class="btn">Refresh</button>
        </form>
      </div>
      <div id="tab2" style="display:none">
        <form action="/refresh/{token}" method="post" enctype="multipart/form-data">
          <input type="hidden" name="method" value="file">
          <div class="upload-area" onclick="document.getElementById('f').click()">Click to upload cookies.txt</div>
          <input type="file" id="f" name="cookies" accept=".txt">
          <button type="submit" class="btn">Refresh</button>
        </form>
      </div>
      <script>function switchTab(n){{[0,1,2].forEach(i => document.getElementById('tab'+i).style.display=i===n?'block':'none');document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',i===n));}}</script>
    """))


@app.post("/refresh/{token}", response_class=HTMLResponse)
async def refresh_upload(token: str, request: Request,
                         cookies: UploadFile = File(None),
                         cookies_text: str = Form(None),
                         method: str = Form("login"),
                         username: str = Form(None),
                         password: str = Form(None)):
    if user_status(token) == "not_found":
        return RedirectResponse("/")

    d = user_dir(token)
    cookies_path = d / "cookies.txt"
    content = None
    if method == "login":
        u = (username or "").strip()
        p = password or ""
        if not u or not p:
            return HTMLResponse(page("Error", f"<h1>Missing Credentials</h1><a href='/refresh/{token}'><button class='btn btn-secondary'>Try Again</button></a>"))
        ok, msg = credential_login(u, p, cookies_path)
        if not ok:
            return HTMLResponse(page("Login Failed", f"<h1>Login Failed</h1><p>{msg}</p><a href='/refresh/{token}'><button class='btn btn-secondary'>Try Again</button></a>"))
        save_credentials(d, u, p)
    elif method == "paste" and cookies_text and cookies_text.strip():
        content = cookies_text.strip().encode("utf-8")
    elif method == "file" and cookies:
        content = await cookies.read()
    elif method != "login":
        return HTMLResponse(page("Error", f"<h1>No Cookies Provided</h1><a href='/refresh/{token}'><button class='btn btn-secondary'>Try Again</button></a>"))

    if content is not None:
        cookies_path = save_cookies(d, content)
        delete_credentials(d)
        if not validate_cookies(cookies_path):
            return HTMLResponse(page("Error", f"<h1>Invalid Cookies</h1><a href='/refresh/{token}'><button class='btn btn-secondary'>Try Again</button></a>"))

    (d / "error.txt").unlink(missing_ok=True)
    (d / "expired.txt").unlink(missing_ok=True)
    threading.Thread(target=run_pipeline, args=(token,), daemon=True).start()
    return RedirectResponse(f"/status/{token}", status_code=303)


# ── Stremio Endpoints ─────────────────────────────────────────────────────────
@app.get("/u/{token}/manifest.json")
async def user_manifest(token: str):
    if user_status(token) == "not_found":
        return JSONResponse({"error": "not found"}, status_code=404, headers=CORS_HEADERS)

    return JSONResponse({
        "id": f"com.khdiamond.user.{token}",
        "version": "2.0.0",
        "name": f"KhDiamond ({token})",
        "description": "KhDiamond's full Khmer catalog with streams unlocked by your account.",
        "logo": "https://khdiamond.net/wp-content/uploads/2025/02/khdiamond-logo.png",
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series"],
        "idPrefixes": ["tt", "khdcat_", f"khd_{token}_"],
        "catalogs": [
            {"type": "movie", "id": f"khdiamond_my_movies_{token}", "name": "KhDiamond — My Movies", "extra": [{"name": "search", "isRequired": False}, {"name": "skip", "isRequired": False}]},
            {"type": "series", "id": f"khdiamond_my_series_{token}", "name": "KhDiamond — My Series", "extra": [{"name": "search", "isRequired": False}, {"name": "skip", "isRequired": False}]},
            {"type": "movie", "id": f"khdiamond_movies_{token}", "name": "KhDiamond — All Movies", "extra": [{"name": "search", "isRequired": False}, {"name": "skip", "isRequired": False}]},
            {"type": "series", "id": f"khdiamond_series_{token}", "name": "KhDiamond — All Series", "extra": [{"name": "search", "isRequired": False}, {"name": "skip", "isRequired": False}]},
        ],
        "behaviorHints": {"adult": False, "p2p": False},
    }, headers=CORS_HEADERS)

def is_purchased_catalog_id(token: str, media_type: str, catalog_id: str) -> bool:
    suffix = "movies" if media_type == "movie" else "series"
    return catalog_id == f"khdiamond_my_{suffix}_{token}"

def parse_skip(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0

def build_catalog_response(token: str, type: str, search: str = "", skip=None, purchased_only: bool = False):
    full_catalog = load_full_catalog()
    personal_catalog = load_catalog(token)
    catalog = full_catalog or personal_catalog
    search = str(search or "").lower().strip()
    skip_value = parse_skip(skip)
    if purchased_only:
        items = purchased_catalog_items(token, type, full_catalog, personal_catalog) if full_catalog else [m for m in personal_catalog if m.get("type") == type]
    else:
        items = [m for m in catalog if m.get("type") == type]
    if search:
        items = [
            m for m in items
            if search in (m.get("title_english") or "").lower()
            or search in (m.get("title_khmer") or "").lower()
            or search in (m.get("slug") or "").lower()
        ]

    metas = []
    seen_ids = set()
    for item in items:
        if full_catalog and not item.get("_fallback_id"):
            meta = stremio_meta(item)
        else:
            fallback_id = (item.get("_fallback_id")
                           or normalize_imdb_id(item.get("imdb_id"))
                           or f"khd_{token}_" + item.get("khd_id", "").removeprefix("khd_"))
            meta = stremio_meta(item)
            meta["id"] = fallback_id
        if not meta["id"] or meta["id"] in seen_ids:
            continue
        seen_ids.add(meta["id"])
        metas.append(meta)
    if skip_value is not None:
        metas = metas[skip_value:skip_value + CATALOG_PAGE_SIZE]
    return JSONResponse({"metas": metas}, headers=CORS_HEADERS)

@app.get("/u/{token}/catalog/{type}/{id}.json")
async def user_catalog(token: str, type: str, id: str, request: Request):
    return build_catalog_response(
        token, type,
        request.query_params.get("search", ""),
        request.query_params.get("skip"),
        is_purchased_catalog_id(token, type, id),
    )

@app.get("/u/{token}/catalog/{type}/{id}/{extra}.json")
async def user_catalog_extra(token: str, type: str, id: str, extra: str):
    """Support native Stremio catalog extras such as search=Doctor%20Strange."""
    extras = parse_qs(extra, keep_blank_values=True)
    return build_catalog_response(
        token, type,
        extras.get("search", [""])[0],
        extras.get("skip", [None])[0],
        is_purchased_catalog_id(token, type, id),
    )

@app.get("/u/{token}/meta/{type}/{id}.json")
async def user_meta(token: str, type: str, id: str):
    full_catalog = load_full_catalog()
    personal = load_catalog(token)
    purchased_items = purchased_catalog_items(token, type, full_catalog, personal)
    item = next((m for m in purchased_items
                 if m.get("type") == type and (item_matches_id(m, token, id) or m.get("_fallback_id") == id or public_item_id(m) == id)), None)
    if item:
        return JSONResponse({"meta": stremio_meta(item, include_videos=True)}, headers=CORS_HEADERS)

    item = find_full_item(full_catalog, type, id) if full_catalog else None
    if item:
        if type == "series":
            purchased_episodes = purchased_series_episodes(item, personal)
            if purchased_episodes:
                item = item.copy()
                item["episodes"] = purchased_episodes
        return JSONResponse({"meta": stremio_meta(item, include_videos=True)}, headers=CORS_HEADERS)

    item = next((m for m in personal
                 if m.get("type") == type and item_matches_id(m, token, id)), None)
    if not item:
        return JSONResponse({"meta": None}, headers=CORS_HEADERS)
    meta = stremio_meta(item, include_videos=True)
    meta["id"] = id
    return JSONResponse({"meta": meta}, headers=CORS_HEADERS)

@app.get("/u/{token}/stream/{type}/{id}.json")
async def user_stream(token: str, type: str, id: str):
    personal = load_catalog(token)
    full_catalog = load_full_catalog()
    full_items = find_full_items(full_catalog, type, id) if full_catalog else []
    if full_items:
        purchased = []
        seen_media_ids = set()
        for full_item in full_items:
            item = find_purchased_item(personal, full_item, id)
            media_id = item.get("movie_id") if item else ""
            if item and media_id and media_id not in seen_media_ids:
                seen_media_ids.add(media_id)
                purchased.append(item)
        streams = []
        seen_streams = set()
        for item in purchased:
            for stream in build_streams(item):
                key = (stream.get("url"), stream.get("title"))
                if key not in seen_streams:
                    seen_streams.add(key)
                    streams.append(stream)
        if streams:
            return JSONResponse({"streams": streams}, headers=CORS_HEADERS)

    base_id, season, episode = split_video_id(id)
    if type == "series" and season is not None and episode is not None:
        clean_slug = base_id.removeprefix("khdcat_").removeprefix(f"khd_{token}_")
        item = next((m for m in personal
                     if m.get("type") == "series"
                     and episode_number(m.get("season")) == season
                     and episode_number(m.get("episode")) == episode
                     and (item_matches_id(m, token, base_id)
                          or clean_slug in str(m.get("series", "") or m.get("slug", ""))
                          or (m.get("imdb_id") and normalize_imdb_id(m.get("imdb_id")) == base_id))), None)
    else:
        item = next((m for m in personal
                     if m.get("type") == type and item_matches_id(m, token, id)), None)

    if not item or not item.get("movie_id"):
        return JSONResponse({"streams": []}, headers=CORS_HEADERS)
    return JSONResponse({"streams": build_streams(item)}, headers=CORS_HEADERS)

@app.get("/u/{token}/{id}.json")
async def user_short_stream(token: str, id: str):
    return await user_stream(token, "movie", id)

# ── Run Server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 KhDiamond UI running on http://0.0.0.0:7003")
    uvicorn.run(app, host="0.0.0.0", port=7003)
