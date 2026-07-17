#!/usr/bin/env python3
"""
user_sync.py — Per-user catalog sync (no Google Sheet)
Reads $USER_DIR/list.json
Fetches metadata from khdiamond pages + TMDB
Writes $CATALOG_PATH (default: $USER_DIR/catalog.json)
"""
import os
import re
import sys
import json
import time
import hashlib
from pathlib import Path

import requests
from bs4 import BeautifulSoup

USER_DIR     = Path(os.environ.get("USER_DIR", "/root/khdiamond"))
CATALOG_PATH = Path(os.environ.get("CATALOG_PATH", str(USER_DIR / "catalog.json")))
TMDB_TOKEN   = os.environ.get("TMDB_ACCESS_TOKEN", "")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
      "Gecko/20100101 Firefox/149.0")

TMDB_HEADERS = {
    "Authorization": f"Bearer {TMDB_TOKEN}",
    "accept": "application/json",
}

CACHE_PATH = USER_DIR / "meta_cache.json"


def load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def scrape_khdiamond_page(url: str, session: requests.Session) -> dict:
    """Scrape poster, title, genres, rating, backdrop from khdiamond page."""
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
    # Poster
    poster_tag = soup.select_one("div.poster img")
    if poster_tag:
        result["poster"] = (poster_tag.get("data-src") or
                            poster_tag.get("data-lazy-src") or
                            poster_tag.get("src", ""))
    # Full title from h1
    h1 = soup.select_one("div.data h1")
    if h1:
        full_title = h1.get_text(strip=True)
        result["title_khmer"] = full_title
        m = re.search(r"[\u2013\u2014\-]\s*([A-Za-z0-9].+)$", full_title)
        if m:
            result["title_english"] = m.group(1).strip()
        else:
            m2 = re.search(r"([A-Za-z0-9][A-Za-z0-9\s\:\!\&\.\,\']+)$", full_title)
            if m2:
                result["title_english"] = m2.group(1).strip()
    # Original title
    for cf in soup.select("div.custom_fields"):
        b = cf.select_one("b.variante")
        if b and "ចំណងជើងដើម" in b.get_text():
            span = cf.select_one("span.valor")
            if span:
                result["original_title"] = span.get_text(strip=True)
    if result["original_title"] and not result["title_english"]:
        result["title_english"] = result["original_title"]
    # Year
    date_tag = soup.select_one("span.date")
    if date_tag:
        year_m = re.search(r"\d{4}", date_tag.get_text(strip=True))
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
    # Genres — keep all including khdiamond tags
    genres = []
    for a in soup.select("div.sgeneros a"):
        g = a.get_text(strip=True)
        if g:
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
    # Backdrop from og:image
    for og in soup.select("meta[property='og:image']"):
        content = og.get("content", "")
        if "image.tmdb.org" in content and len(content) > 40:
            result["backdrop"] = content
            break
    return result

def fetch_tmdb_metadata(title: str, year: str, kind: str) -> dict:
    """Fetch IMDB ID and metadata from TMDB."""
    if not TMDB_TOKEN:
        return {}
    try:
        media_type = "tv" if kind in ("tvshows", "episode", "series") else "movie"
        params = {"query": title, "language": "en-US"}
        if year:
            params["year"] = year
        r = requests.get(
            f"https://api.themoviedb.org/3/search/{media_type}",
            headers=TMDB_HEADERS, params=params, timeout=10
        )
        if r.status_code != 200:
            return {}
        results = r.json().get("results", [])
        if not results:
            return {}
        top = results[0]
        tmdb_id = top.get("id")

        # Get external IDs (for IMDB ID)
        ext = requests.get(
            f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids",
            headers=TMDB_HEADERS, timeout=10
        )
        imdb_id = ""
        backdrop = ""
        rating = ""
        if ext.status_code == 200:
            imdb_id = ext.json().get("imdb_id", "")

        backdrop_path = top.get("backdrop_path", "")
        if backdrop_path:
            backdrop = f"https://image.tmdb.org/t/p/w1280{backdrop_path}"

        poster_path = top.get("poster_path", "")
        tmdb_poster = ""
        if poster_path:
            tmdb_poster = f"https://image.tmdb.org/t/p/w500{poster_path}"

        rating = str(round(top.get("vote_average", 0), 1))

        # Get runtime from details endpoint
        runtime = ""
        details = requests.get(
            f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
            headers=TMDB_HEADERS, timeout=10
        )
        if details.status_code == 200:
            d = details.json()
            if media_type == "movie":
                mins = d.get("runtime")
                if mins:
                    runtime = f"{mins} min"
            else:
                ep_mins = d.get("episode_run_time", [])
                if ep_mins:
                    runtime = f"{ep_mins[0]} min"

        return {
            "imdb_id": imdb_id,
            "tmdb_id": str(tmdb_id),
            "backdrop": backdrop,
            "tmdb_poster": tmdb_poster,
            "imdb_rating": rating,
            "runtime": runtime,
        }
    except Exception as e:
        print(f"    TMDB error for '{title}': {e}")
        return {}


def make_khd_id(movie_id: str) -> str:
    return f"khd_{movie_id}"


def main():
    list_path = USER_DIR / "list.json"
    if not list_path.exists():
        sys.exit(f"❌ {list_path} missing — run user_resolve.py first.")

    items = json.loads(list_path.read_text())
    print(f"✓ Read {len(items)} items from list.json")

    cache = load_cache()
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    catalog = []
    for i, item in enumerate(items, 1):
        movie_id   = item.get("movie_id", "")
        movie_id_4k = item.get("movie_id_4k", "")
        title      = item.get("title", "")
        kind       = item.get("kind", "movies")
        year       = item.get("year", "")
        page_url   = item.get("page_url", "")
        slug       = item.get("slug", "")
        series_slug = item.get("series", "")

        if not movie_id:
            continue

        cache_key = hashlib.md5(movie_id.encode()).hexdigest()

        cached = cache.get(cache_key)
        # Older resolver output dropped the parent-series slug. That left
        # episode entries cached without posters; refresh those entries once.
        if cached and (kind != "episode" or cached.get("poster")):
            print(f"  [{i:>3}/{len(items)}] reused  {title[:60]}")
            entry = cached
            entry["movie_id"] = movie_id
            entry["movie_id_4k"] = movie_id_4k
            catalog.append(entry)
            continue

        print(f"  [{i:>3}/{len(items)}] scraped {title[:60]}")

        # Scrape khdiamond page
        kh_meta = {}
        if page_url:
            # For episodes, scrape series page for poster instead of episode page
            if kind == 'episode' and (series_slug or slug):
                # Extract series slug: 'twelve-1x1' -> 'twelve', 's-line-1x1' -> 's-line'
                if not series_slug:
                    m = re.match(r'^(.+?)-\d+x\d+$', slug)
                    series_slug = m.group(1) if m else slug
                series_url = f'https://khdiamond.net/tvshows/{series_slug}/'
                kh_meta = scrape_khdiamond_page(series_url, session)
            else:
                kh_meta = scrape_khdiamond_page(page_url, session)
            time.sleep(0.3)

        # Determine English title for TMDB search
        title_english = title
        if "–" in title:
            title_english = title.split("–")[-1].strip()
        elif "-" in title:
            title_english = title.split("-")[-1].strip()

        # Fetch TMDB metadata
        tmdb_meta = fetch_tmdb_metadata(title_english, year or kh_meta.get("year", ""), kind)
        time.sleep(0.3)

        # Determine stremio type
        if kind in ("tvshows", "series"):
            stype = "series"
        elif kind == "episode":
            stype = "series"
        else:
            stype = "movie"

        # Use TMDB poster as fallback
        poster = kh_meta.get("poster") or tmdb_meta.get("tmdb_poster", "")

        entry = {
            "khd_id":       make_khd_id(movie_id),
            "movie_id":     movie_id,
            "movie_id_4k":  movie_id_4k,
            "slug":         slug,
            "type":         stype,
            "title_khmer":  kh_meta.get("title_khmer", title),
            "title_english": title_english,
            "year":         year or kh_meta.get("year", ""),
            "poster":       poster,
            "backdrop":     tmdb_meta.get("backdrop", ""),
            "genres":       kh_meta.get("genres", []),
            "overview":     kh_meta.get("overview", ""),
            "imdb_id":      tmdb_meta.get("imdb_id", ""),
            "tmdb_id":      tmdb_meta.get("tmdb_id", ""),
            "imdb_rating":  kh_meta.get("imdb_rating") or tmdb_meta.get("imdb_rating", ""),
            "runtime":      kh_meta.get("runtime") or tmdb_meta.get("runtime", ""),
        }

        cache[cache_key] = entry
        catalog.append(entry)

    save_cache(cache)

    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    print(f"\n✓ catalog.json written → {CATALOG_PATH}")
    print(f"   Total  : {len(catalog)}")
    print(f"   Movies : {sum(1 for e in catalog if e['type'] == 'movie')}")
    print(f"   Series : {sum(1 for e in catalog if e['type'] == 'series')}")


if __name__ == "__main__":
    main()
