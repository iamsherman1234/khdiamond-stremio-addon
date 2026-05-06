"""
sync_catalog.py
───────────────
Pipeline Step 5 — runs after the downloader.

Strategy:
  1. Read 'list' tab from Google Sheet (movie_id + title)
  2. Read 'library_raw' tab to get page_url for each item
  3. Scrape each khdiamond page for accurate metadata:
       poster, title, original_title, date, runtime, rating,
       genres, description, imdb_rating, backdrop
  4. Search TMDB with original_title to get IMDB ID only
  5. Write catalog.json to /root/khdiamond/catalog.json
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
from bs4 import BeautifulSoup

from drive_manager import get_gspread_client

# ─────────────────────────── Config ──────────────────────────────────────────

SPREADSHEET_ID = "1gAjrURaRX3ce1gf-KyUw2UOlwYX3aEYc_7YnQD6T-5g"
LIST_TAB       = "list"
RAW_TAB        = "library_raw"
CATALOG_OUT    = Path("/root/khdiamond/catalog.json")
COOKIES_PATH   = Path(os.environ.get("COOKIES_PATH", "/tmp/cookies.txt"))

TMDB_TOKEN = os.environ.get(
    "TMDB_ACCESS_TOKEN",
    "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI3YzAxN2Q1OGY1NDEwOTU3YWFlOTllNDk5NTIxZTk1YiIsIm5iZiI6MTc2NzUwMjg2Ny45NjMsInN1YiI6IjY5NTlmNDEzYjU3ZWRjZWFhYmQ3OTY2MiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.bzpgjaNeTfbBntDDJZUIqLYgf0ww_I3hf30xC0i2hRg"
)
TMDB_BASE    = "https://api.themoviedb.org/3"
TMDB_IMG     = "https://image.tmdb.org/t/p"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
      "Gecko/20100101 Firefox/149.0")

SCRAPE_DELAY = 0.5   # seconds between page fetches
TMDB_DELAY   = 0.25  # seconds between TMDB API calls

# ─────────────────────────── HTTP session ────────────────────────────────────

def make_session() -> requests.Session:
    jar = MozillaCookieJar(str(COOKIES_PATH))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = jar
    s.headers.update({"User-Agent": UA, "Referer": "https://khdiamond.net/"})
    return s


# ─────────────────────────── KhDiamond scraper ───────────────────────────────

def scrape_page(session: requests.Session, url: str) -> dict:
    """
    Scrape a khdiamond movie or tvshow page.
    Returns dict with: poster, title_khmer, title_english, original_title,
                       year, runtime, age_rating, genres, overview,
                       imdb_rating, backdrop
    """
    result = {
        "poster": "", "title_khmer": "", "title_english": "",
        "original_title": "", "year": "", "runtime": "", "age_rating": "",
        "genres": [], "overview": "", "imdb_rating": "", "backdrop": "",
    }

    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"    HTTP {r.status_code} for {url}")
            return result
    except Exception as e:
        print(f"    Fetch error {url}: {e}")
        return result

    soup = BeautifulSoup(r.text, "html.parser")

    # Poster — khdiamond's own image
    poster_tag = soup.select_one("div.poster img")
    if poster_tag:
        result["poster"] = poster_tag.get("src", "")

    # Full title from h1
    h1 = soup.select_one("div.data h1")
    if h1:
        full_title = h1.get_text(strip=True)
        result["title_khmer"] = full_title

        # Split Khmer and English parts
        # Pattern: Khmer text – English title
        m = re.search(r"[\u2013\u2014\-]\s*([A-Za-z0-9].+)$", full_title)
        if m:
            result["title_english"] = m.group(1).strip()
        else:
            # No dash — try to find English at the end
            m2 = re.search(r"([A-Za-z0-9][A-Za-z0-9\s\:\!\&\.\,\']+)$", full_title)
            if m2:
                result["title_english"] = m2.group(1).strip()

    # Original title from custom fields
    for cf in soup.select("div.custom_fields"):
        b = cf.select_one("b.variante")
        if b and "ចំណងជើងដើម" in b.get_text():
            span = cf.select_one("span.valor")
            if span:
                result["original_title"] = span.get_text(strip=True)

    # Use original_title as title_english if better
    if result["original_title"] and not result["title_english"]:
        result["title_english"] = result["original_title"]

    # Year from date
    date_tag = soup.select_one("span.date")
    if date_tag:
        date_text = date_tag.get_text(strip=True)
        year_m = re.search(r"\d{4}", date_text)
        if year_m:
            result["year"] = year_m.group(0)

    # Runtime
    runtime_tag = soup.select_one("span.runtime")
    if runtime_tag:
        result["runtime"] = runtime_tag.get_text(strip=True)

    # Age rating
    rated_tag = soup.select_one("span.rated")
    if rated_tag:
        result["age_rating"] = rated_tag.get_text(strip=True)

    # Genres — filter out Khmer-only categories
    SKIP_GENRES = {
        "គិតតម្លៃ-paid", "និយាយខ្មែរ", "អក្សរខ្មែរ", "ហូលីវូត",
        "ភាគកូរ៉េ", "ភាគចិន", "ភាគជប៉ុន", "ភាគ Anime",
    }
    genres = []
    for a in soup.select("div.sgeneros a"):
        g = a.get_text(strip=True)
        if g not in SKIP_GENRES and not any(
            c >= "\u1780" and c <= "\u17ff" for c in g
        ):
            genres.append(g)
    result["genres"] = genres

    # Description
    desc_tag = soup.select_one("div.wp-content p")
    if desc_tag:
        result["overview"] = desc_tag.get_text(strip=True)

    # IMDB rating
    imdb_tag = soup.select_one("#repimdb strong")
    if imdb_tag:
        result["imdb_rating"] = imdb_tag.get_text(strip=True)

    # Backdrop from og:image (TMDB hosted)
    for og in soup.select("meta[property='og:image']"):
        content = og.get("content", "")
        if "image.tmdb.org" in content and len(content) > 40:
            result["backdrop"] = content
            break

    return result


# ─────────────────────────── TMDB — IMDB ID only ─────────────────────────────

def tmdb_headers() -> dict:
    return {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "Accept": "application/json",
    }


def get_imdb_id(title: str, media_type: str) -> str:
    """Search TMDB for IMDB ID only. Returns '' if not found."""
    if not title:
        return ""

    endpoint = "tv" if media_type == "series" else "movie"
    for ep in [endpoint, "multi"]:
        try:
            r = requests.get(
                f"{TMDB_BASE}/search/{ep}",
                headers=tmdb_headers(),
                params={"query": title, "language": "en-US", "page": 1},
                timeout=10,
            )
            if not r.ok:
                continue
            results = r.json().get("results", [])
            if not results:
                continue

            tmdb_id = results[0].get("id")
            time.sleep(TMDB_DELAY)

            # Fetch external IDs
            detail_ep = "tv" if ep == "tv" or (
                ep == "multi" and results[0].get("media_type") == "tv"
            ) else "movie"
            r2 = requests.get(
                f"{TMDB_BASE}/{detail_ep}/{tmdb_id}/external_ids",
                headers=tmdb_headers(),
                timeout=10,
            )
            if r2.ok:
                return r2.json().get("imdb_id", "")
        except Exception as e:
            print(f"    TMDB error: {e}")
        time.sleep(TMDB_DELAY)

    return ""


# ─────────────────────────── Main ────────────────────────────────────────────

def main():
    if not COOKIES_PATH.exists():
        raise SystemExit(f"Cookies not found at {COOKIES_PATH}")

    # ── Load Sheet data ───────────────────────────────────────────────────────
    print("-> Reading Google Sheet...")
    gc = get_gspread_client()
    ss = gc.open_by_key(SPREADSHEET_ID)

    list_rows = ss.worksheet(LIST_TAB).get_all_records()
    raw_rows  = ss.worksheet(RAW_TAB).get_all_records()
    print(f"   list tab : {len(list_rows)} rows")
    print(f"   raw tab  : {len(raw_rows)} rows")

    # Build lookup: slug/title → page_url + kind from library_raw
    # For episodes, map series slug to series page_url
    raw_by_movie_slug: dict[str, dict] = {}
    series_pages: dict[str, dict] = {}  # series_slug → raw row

    for row in raw_rows:
        kind = row.get("kind", "")
        if kind == "tvshows":
            series_pages[row["slug"]] = row
        elif kind == "movies":
            raw_by_movie_slug[row["slug"]] = row

    # Build lookup: movie_id → raw row (via list tab title matching)
    # list tab has movie_id + title; library_raw has slug + page_url
    # We match by using the slug embedded in page_url
    raw_by_page_url: dict[str, dict] = {
        row["page_url"]: row for row in raw_rows
    }

    # Load existing catalog for IMDB ID cache (avoid re-fetching)
    existing: dict[str, dict] = {}
    if CATALOG_OUT.exists():
        try:
            for item in json.loads(CATALOG_OUT.read_text()):
                existing[item["movie_id"]] = item
            print(f"   cached   : {len(existing)} entries\n")
        except Exception:
            pass

    session = make_session()
    catalog = []

    # Group episodes by series page_url so we only scrape each series once
    series_cache: dict[str, dict] = {}

    for i, row in enumerate(list_rows, 1):
        movie_id  = str(row.get("movie_id", "")).strip()
        movie_id_4k = str(row.get("movie_id_4k", "")).strip()
        raw_title = str(row.get("title", "")).strip()

        if not movie_id or not raw_title:
            continue

        khd_id = f"khd_{movie_id}"

        # Detect media type from title patterns
        is_episode = bool(re.search(r"S\d+E\d+", raw_title))
        media_type = "series" if is_episode else "movie"

        print(f"  [{i:>3}/{len(list_rows)}] ", end="", flush=True)

        # ── Reuse if already cached AND has imdb_id ───────────────────────────
        if movie_id in existing and existing[movie_id].get("imdb_id"):
            entry = existing[movie_id].copy()
            entry["movie_id_4k"] = movie_id_4k  # always update from Sheet
            catalog.append(entry)
            print(f"reused  {raw_title[:60]}")
            continue

        # ── Find page_url ─────────────────────────────────────────────────────
        # Episodes: find series slug from title (e.g. "Twelve — S01E01 — ...")
        page_url = ""
        if is_episode:
            # Extract series name before " — S01E01"
            series_name = re.sub(r"\s*[\u2013\u2014]\s*S\d+E\d+.*$", "", raw_title).strip()
            # Find matching series in library_raw
            for slug, srow in series_pages.items():
                if slug in series_name.lower() or series_name.lower() in srow.get("title", "").lower():
                    page_url = srow["page_url"]
                    break
            # Fallback: search by title keyword
            if not page_url:
                # Try matching English part
                en_m = re.search(r"[\u2013\u2014]\s*([A-Za-z0-9][^—\u2013\u2014]+?)(?:\s*[\u2013\u2014]|$)", raw_title)
                if en_m:
                    en_name = en_m.group(1).strip().lower()
                    for slug, srow in series_pages.items():
                        if en_name in srow.get("title", "").lower() or en_name in slug:
                            page_url = srow["page_url"]
                            break
        else:
            # Movie: find in raw_rows by matching title
            for rrow in raw_rows:
                if rrow.get("kind") == "movies" and rrow.get("title", "") == raw_title:
                    page_url = rrow["page_url"]
                    break

        if not page_url:
            print(f"no page_url for: {raw_title[:60]}")
            # Keep existing entry without imdb_id if available
            if movie_id in existing:
                catalog.append(existing[movie_id])
            else:
                catalog.append({
                    "movie_id": movie_id, "khd_id": khd_id,
                    "title_khmer": raw_title, "title_english": raw_title,
                    "type": media_type, "imdb_id": "", "poster": "",
                    "backdrop": "", "overview": "", "year": "",
                    "imdb_rating": "", "genres": [], "runtime": "",
                })
            continue

        # ── Scrape khdiamond page ─────────────────────────────────────────────
        if page_url in series_cache:
            meta = series_cache[page_url]
            print(f"cached  {raw_title[:55]}")
        else:
            meta = scrape_page(session, page_url)
            if is_episode:
                series_cache[page_url] = meta
            time.sleep(SCRAPE_DELAY)
            print(f"scraped {raw_title[:55]}", end=" ")

        # ── Get IMDB ID from TMDB ─────────────────────────────────────────────
        imdb_id = existing.get(movie_id, {}).get("imdb_id", "")
        if not imdb_id:
            search_title = meta.get("original_title") or meta.get("title_english") or raw_title
            # Clean episode markers
            search_title = re.sub(r"\s*[\u2013\u2014]\s*S\d+E\d+.*$", "", search_title).strip()
            search_title = re.sub(r"[\u1780-\u17ff]", "", search_title).strip()
            imdb_id = get_imdb_id(search_title, media_type)
            print(f"IMDB:{imdb_id or 'n/a'}")
        else:
            print(f"IMDB:{imdb_id} (cached)")

        entry = {
            "movie_id":     movie_id,
            "movie_id_4k":  movie_id_4k,
            "khd_id":       khd_id,
            "title_khmer":  meta.get("title_khmer") or raw_title,
            "title_english": meta.get("title_english") or raw_title,
            "type":         media_type,
            "imdb_id":      imdb_id,
            "poster":       meta.get("poster", ""),
            "backdrop":     meta.get("backdrop", ""),
            "overview":     meta.get("overview", ""),
            "year":         meta.get("year", ""),
            "imdb_rating":  meta.get("imdb_rating", ""),
            "genres":       meta.get("genres", []),
            "runtime":      meta.get("runtime", ""),
            "age_rating":   meta.get("age_rating", ""),
        }
        catalog.append(entry)

    # ── Write catalog.json ────────────────────────────────────────────────────
    CATALOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_OUT.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    matched   = sum(1 for e in catalog if e.get("imdb_id"))
    unmatched = sum(1 for e in catalog if not e.get("imdb_id"))

    print(f"\ncatalog.json written -> {CATALOG_OUT}")
    print(f"   Total   : {len(catalog)}")
    print(f"   Matched : {matched}")
    print(f"   No match: {unmatched}")
    
    # Upload to Cloudflare KV
    try:
        import subprocess
        result = subprocess.run(
            ["python3", "/root/khdiamond/scripts/upload_catalog_to_kv.py"],
            env={**os.environ}, capture_output=True, text=True
        )
        print(result.stdout.strip())
    except Exception as e:
        print(f"⚠ KV upload skipped: {e}")

if __name__ == "__main__":
    main()
