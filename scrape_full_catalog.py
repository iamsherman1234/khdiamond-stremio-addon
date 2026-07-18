#!/usr/bin/env python3
"""
scrape_full_catalog.py — Scrape full public KhDiamond catalog
No login required — scrapes public movie/series listing pages.

Sources:
  https://khdiamond.net/movies/page/{n}/
  https://khdiamond.net/tvshows/page/{n}/

Output:
  /root/khdiamond/full_catalog.json

Enriched with TMDB: English title, year, backdrop, genres, overview, IMDB ID, runtime
"""
import os
import re
import sys
import json
import time
import hashlib
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from http.cookiejar import MozillaCookieJar
import re as _re

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_PATH  = Path(os.environ.get("FULL_CATALOG_PATH", "/root/khdiamond/full_catalog.json"))
CACHE_PATH   = Path(os.environ.get("FULL_CATALOG_CACHE", "/root/khdiamond/full_catalog_cache.json"))
TMDB_TOKEN   = os.environ.get("TMDB_ACCESS_TOKEN", "")

SOURCES = [
    {"kind": "movie",  "type": "movie",  "base_url": "https://khdiamond.net/movies/page/{}/"},
    {"kind": "tvshow", "type": "series", "base_url": "https://khdiamond.net/tvshows/page/{}/"},
]

FREE_GENRE_URL = "https://khdiamond.net/genre/%E1%9E%A5%E1%9E%8F%E1%9E%82%E1%9E%B7%E1%9E%8F%E1%9E%90%E1%9F%92%E1%9E%9B%E1%9F%83/page/{}/"

MANUAL_METADATA_BY_SLUG = {
    "hoppers": {"imdb_id": "tt26443616", "year": "2026"},
    "sitaare-zameen-par": {"imdb_id": "tt27235410", "year": "2025"},
    "harry-potter-and-the-half-blood-prince": {"imdb_id": "tt0417741", "year": "2009"},
    "ready-player-one": {"imdb_id": "tt1677720", "year": "2018"},
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
      "Gecko/20100101 Firefox/149.0")

TMDB_HEADERS = {
    "Authorization": f"Bearer {TMDB_TOKEN}",
    "accept": "application/json",
}

PAGE_DELAY  = 0.5
TMDB_DELAY  = 0.3
CACHE_VERSION = 3
TMDB_MIN_SCORE = float(os.environ.get("TMDB_MIN_MATCH_SCORE", "80"))
RESOLVE_FREE_STREAMS = os.environ.get("FULL_CATALOG_RESOLVE_FREE_STREAMS", "0").lower() in {"1", "true", "yes"}
MIN_CATALOG_RATIO = float(os.environ.get("FULL_CATALOG_MIN_PREVIOUS_RATIO", "0.90"))
ALLOW_LARGE_SHRINK = os.environ.get("FULL_CATALOG_ALLOW_LARGE_SHRINK", "0").lower() in {"1", "true", "yes"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://khdiamond.net/"})
    return s


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def existing_catalog_count() -> int:
    if not OUTPUT_PATH.exists():
        return 0
    try:
        value = json.loads(OUTPUT_PATH.read_text())
        return len(value) if isinstance(value, list) else 0
    except Exception:
        return 0


def catalog_size_is_safe(current: int, previous: int) -> bool:
    return previous <= 0 or current >= previous * MIN_CATALOG_RATIO


def write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def save_cache(cache: dict):
    write_json_atomic(CACHE_PATH, cache)


def slug_from_url(url: str) -> str:
    """Extract slug from khdiamond URL."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def valid_poster_url(value: str) -> bool:
    value = str(value or "").strip()
    if not value.startswith(("http://", "https://")):
        return False
    lowered = value.lower().split("?", 1)[0]
    filename = lowered.rsplit("/", 1)[-1]
    return not (
        "/themes/dooplay/assets/img/" in lowered
        or re.fullmatch(r"s{3,}\d*\.(?:png|jpe?g|webp)", filename)
    )


def source_signature(item: dict, stype: str) -> str:
    """Identify the current page, not merely its reusable opaque slug."""
    payload = "\n".join((
        str(stype or ""),
        str(item.get("page_url") or "").rstrip("/"),
        " ".join(str(item.get("title_khmer") or "").split()),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_entry_is_current(entry: dict, item: dict, stype: str) -> bool:
    return (
        entry.get("_cache_version") == CACHE_VERSION
        and entry.get("_source_signature") == source_signature(item, stype)
        and entry.get("slug") == item.get("slug")
        and entry.get("type") == stype
    )


def apply_manual_metadata(entry: dict) -> dict:
    overrides = MANUAL_METADATA_BY_SLUG.get(entry.get("slug", ""))
    if not overrides:
        return entry
    for key, value in overrides.items():
        if value and not entry.get(key):
            entry[key] = value
    return entry


def scrape_listing_page(session: requests.Session, url: str) -> list[dict]:
    """Scrape a single listing page. Returns list of basic movie dicts."""
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 404:
            return None  # No more pages
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} for {url}")
            return []
    except Exception as e:
        print(f"  Fetch error {url}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    articles = soup.find_all("article")
    if not articles:
        return None  # No more pages

    items = []
    for art in articles:
        # Get page URL from h3 link
        h3 = art.find("h3")
        if not h3:
            continue
        link = h3.find("a", href=True)
        if not link:
            continue

        page_url = link["href"]
        title_khmer = link.get_text(strip=True)
        slug = slug_from_url(page_url)

        # Get real poster (2nd img tag)
        imgs = art.select("div.poster img")
        poster = ""
        for img in imgs:
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src", "")
            if valid_poster_url(src):
                poster = src
                break

        # Rating from listing
        rating_div = art.select_one("div.rating")
        rating = rating_div.get_text(strip=True) if rating_div else ""

        items.append({
            "slug":        slug,
            "title_khmer": title_khmer,
            "page_url":    page_url,
            "poster":      poster,
            "rating":      rating,
        })

    return items


def text_tokens(value: str) -> set[str]:
    return {t for t in _re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(t) > 3}


def normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = _re.sub(r"[^\w]+", " ", value, flags=_re.UNICODE).replace("_", " ")
    value = " ".join(value.split())
    return _re.sub(r"^(the|a|an)\s+", "", value).strip()


def score_tmdb_candidate(candidate: dict, title: str, year: str = "", overview_hint: str = "") -> float:
    query_title = normalized_title(title)
    names = [candidate.get("title"), candidate.get("name"), candidate.get("original_title"), candidate.get("original_name")]
    candidate_titles = [normalized_title(n) for n in names if n]
    score = 0.0

    similarities = [SequenceMatcher(None, query_title, t).ratio()
                    for t in candidate_titles if query_title and t]
    best_similarity = max(similarities, default=0.0)
    if best_similarity == 1.0:
        score += 100
    elif best_similarity >= 0.88:
        score += 70 * best_similarity
    elif query_title and any(query_title in t or t in query_title for t in candidate_titles):
        score += 30

    release = candidate.get("release_date") or candidate.get("first_air_date") or ""
    candidate_year = release[:4] if release else ""
    if year and candidate_year == str(year):
        score += 35
    elif year and candidate_year:
        score -= 45

    hint_tokens = text_tokens(overview_hint)
    overview_tokens = text_tokens(candidate.get("overview", ""))
    if hint_tokens and overview_tokens:
        overlap = len(hint_tokens & overview_tokens) / max(1, len(hint_tokens))
        score += overlap * 120

    score += min(float(candidate.get("popularity") or 0), 20) / 10
    return score


def acceptable_tmdb_candidate(candidate: dict, title: str, year: str, score: float) -> bool:
    """Reject plausible-looking but unsafe matches; a blank ID is safer than a wrong ID."""
    query_title = normalized_title(title)
    if not query_title:
        return False
    candidate_titles = [
        normalized_title(candidate.get(key, ""))
        for key in ("title", "name", "original_title", "original_name")
    ]
    candidate_titles = [value for value in candidate_titles if value]
    best_similarity = max(
        (SequenceMatcher(None, query_title, value).ratio() for value in candidate_titles),
        default=0.0,
    )
    release = candidate.get("release_date") or candidate.get("first_air_date") or ""
    candidate_year = release[:4]
    if year and candidate_year and str(year) != candidate_year:
        return False
    return score >= TMDB_MIN_SCORE and best_similarity >= 0.88


def fetch_tmdb(title: str, year: str, media_type: str, overview_hint: str = "") -> dict:
    """Fetch metadata from TMDB. Returns enriched dict."""
    if not TMDB_TOKEN:
        return {}
    try:
        params = {"query": title, "language": "en-US"}
        if year:
            params["year" if media_type == "movie" else "first_air_date_year"] = year
        r = requests.get(
            f"https://api.themoviedb.org/3/search/{media_type}",
            headers=TMDB_HEADERS, params=params, timeout=10
        )
        if r.status_code != 200 or not r.json().get("results"):
            return {}

        results = r.json()["results"]
        scored = [(score_tmdb_candidate(item, title, year, overview_hint), item)
                  for item in results]
        best_score, top = max(scored, key=lambda pair: pair[0])
        if not acceptable_tmdb_candidate(top, title, year, best_score):
            print(f"    TMDB rejected low-confidence match for '{title}' (score {best_score:.1f})")
            return {}
        tmdb_id = top.get("id")
        time.sleep(TMDB_DELAY)

        # Get details for runtime
        det = requests.get(
            f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
            headers=TMDB_HEADERS, timeout=10
        )
        runtime = ""
        if det.status_code == 200:
            d = det.json()
            if media_type == "movie":
                mins = d.get("runtime")
                if mins:
                    runtime = f"{mins} min"
            else:
                ep_mins = d.get("episode_run_time", [])
                if ep_mins:
                    runtime = f"{ep_mins[0]} min"
        time.sleep(TMDB_DELAY)

        # Get external IDs for IMDB
        ext = requests.get(
            f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids",
            headers=TMDB_HEADERS, timeout=10
        )
        imdb_id = ""
        if ext.status_code == 200:
            imdb_id = ext.json().get("imdb_id", "")
        time.sleep(TMDB_DELAY)

        # English title
        title_english = top.get("title") or top.get("name") or title

        # Year
        release = top.get("release_date") or top.get("first_air_date") or ""
        tmdb_year = release[:4] if release else ""

        # Poster + backdrop
        poster_path = top.get("poster_path", "")
        tmdb_poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
        backdrop_path = top.get("backdrop_path", "")
        backdrop = f"https://image.tmdb.org/t/p/w1280{backdrop_path}" if backdrop_path else ""

        # Genres
        genres = []  # genre_ids are ints, use details endpoint
        # genre_ids need lookup — use details endpoint genres instead
        det_genres = []
        if det.status_code == 200:
            det_genres = [g["name"] for g in det.json().get("genres", [])]

        # Overview
        overview = top.get("overview", "")

        # Rating
        vote = top.get("vote_average", 0)
        imdb_rating = str(round(vote, 1)) if vote else ""

        return {
            "title_english": title_english,
            "year":          tmdb_year,
            "tmdb_id":       str(tmdb_id),
            "imdb_id":       imdb_id,
            "tmdb_poster":   tmdb_poster,
            "backdrop":      backdrop,
            "genres":        det_genres,
            "overview":      overview,
            "imdb_rating":   imdb_rating,
            "runtime":       runtime,
            "match_score":   round(best_score, 1),
        }
    except Exception as e:
        print(f"    TMDB error for '{title}': {e}")
        return {}


def scrape_khmer_overview(session: requests.Session, page_url: str) -> str:
    """Scrape Khmer overview from individual movie/series page."""
    return scrape_page_details(session, page_url).get("overview", "")


def scrape_page_details(session: requests.Session, page_url: str) -> dict:
    """Scrape stable detail-page metadata that listing/TMDB can miss."""
    details = {"overview": "", "poster": "", "year": "", "runtime": "",
               "title_khmer": "", "original_title": "", "status_code": 0}
    try:
        r = None
        for attempt in range(3):
            r = session.get(page_url, timeout=20)
            details["status_code"] = r.status_code
            if r.status_code not in {429, 500, 502, 503, 504}:
                break
            time.sleep(1.5 * (attempt + 1))
        if r is None:
            return details
        if r.status_code != 200:
            return details
        soup = BeautifulSoup(r.text, "html.parser")
        h1 = soup.select_one("div.data h1, h1")
        if h1:
            details["title_khmer"] = h1.get_text(" ", strip=True)
        for field in soup.select("div.custom_fields"):
            label = field.select_one("b.variante")
            value = field.select_one("span.valor")
            if label and value and "ចំណងជើងដើម" in label.get_text(" ", strip=True):
                details["original_title"] = value.get_text(" ", strip=True)
                break
        for poster in soup.select("div.sheader div.poster img, div.poster img"):
            src = (poster.get("data-src") or poster.get("data-lazy-src")
                   or poster.get("data-original") or poster.get("src", ""))
            if valid_poster_url(src):
                details["poster"] = src
                break
        date_tag = soup.select_one("span.date")
        if date_tag:
            year_m = re.search(r"\d{4}", date_tag.get_text(strip=True))
            if year_m:
                details["year"] = year_m.group(0)
        runtime_tag = soup.select_one("span.runtime")
        if runtime_tag:
            details["runtime"] = runtime_tag.get_text(strip=True)
        desc = soup.select_one("div.wp-content p")
        if desc:
            details["overview"] = desc.get_text(strip=True)
    except Exception:
        pass
    return details


def extract_english_from_khmer_title(title: str) -> str:
    """Try to extract English part from mixed Khmer-English title."""
    title = re.sub(r"\([^A-Za-z0-9)]*\)", "", title).strip()
    m = re.search(r"[–\-]\s*([A-Za-z0-9].+)$", title)
    if m:
        return m.group(1).strip()
    parts = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s\:\!\&\.\,\'\?]+", title)
    if parts:
        return max((p.strip() for p in parts), key=len).strip(" -–")
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────

COOKIES_PATH = Path(os.environ.get("COOKIES_PATH", "/root/khdiamond/cookies.txt"))
AJAX_URL = "https://khdiamond.net/wp-admin/admin-ajax.php"
EMBED_ID_RE = _re.compile(r"player\.khdiamond\.net/\d+/\d+/([A-Za-z0-9]+)")
POSTID_RE = _re.compile(r"postid-(\d+)")
EPISODE_LINK_RE = _re.compile(r"href=[\"\'](https?://khdiamond\.net/episodes/[^\"\']+/)[\"\']")
SEASON_EPISODE_RE = _re.compile(r"S(\d+)\s*-\s*E(\d+)", _re.I)


def make_auth_session() -> requests.Session:
    """Session with cookies for resolving free movie streams."""
    if not COOKIES_PATH.exists():
        return None
    jar = MozillaCookieJar(str(COOKIES_PATH))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = jar
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://khdiamond.net/",
        "X-Requested-With": "XMLHttpRequest",
    })
    return s



def valid_movie_id(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value) and value not in {"error", "undefined", "null", "none"} and bool(_re.fullmatch(r"[A-Za-z0-9]+", value))


def scrape_series_episodes(session: requests.Session, page_url: str) -> list[dict]:
    """Scrape episode links/season/episode labels from a KhDiamond series page."""
    try:
        r = session.get(page_url, timeout=20)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    episodes = []
    seen = set()
    for card in soup.select("div.video-card, ul.episodios li"):
        link = card.select_one("a[href*='/episodes/']")
        if not link:
            continue
        ep_url = link.get("href", "")
        if not ep_url or ep_url in seen:
            continue
        seen.add(ep_url)

        title_el = card.select_one("div.title, div.episodiotitle a")
        title = title_el.get_text(" ", strip=True) if title_el else slug_from_url(ep_url)
        meta_text = card.get_text(" ", strip=True)
        se = SEASON_EPISODE_RE.search(meta_text)
        season = int(se.group(1)) if se else 1
        episode = int(se.group(2)) if se else len(episodes) + 1
        thumb_el = card.select_one("img[src]")
        date_el = card.select_one("span.date")
        episodes.append({
            "id": "",
            "season": season,
            "episode": episode,
            "title": title,
            "page_url": ep_url,
            "thumbnail": thumb_el.get("src", "") if thumb_el else "",
            "released": date_el.get_text(strip=True) if date_el else "",
            "movie_id": "",
            "movie_id_4k": "",
        })
    return episodes


def resolve_episode_stream(auth_session, episode: dict) -> dict:
    if not auth_session:
        return {"movie_id": "", "movie_id_4k": ""}
    page_url = episode.get("page_url", "")
    try:
        r = auth_session.get(page_url, timeout=20)
        m = POSTID_RE.search(r.text)
        if not m:
            return {"movie_id": "", "movie_id_4k": ""}
        post_id = m.group(1)
        payload = {"action": "doo_player_ajax", "post": post_id, "nume": "1", "type": "tv"}
        resp = auth_session.post(AJAX_URL, data=payload, headers={"Referer": page_url}, timeout=20)
        if resp.status_code != 200:
            return {"movie_id": "", "movie_id_4k": ""}
        embed = resp.json().get("embed_url", "")
        mid = EMBED_ID_RE.search(embed)
        movie_id = mid.group(1) if mid and valid_movie_id(mid.group(1)) else ""

        movie_id_4k = ""
        payload["nume"] = "2"
        resp4k = auth_session.post(AJAX_URL, data=payload, headers={"Referer": page_url}, timeout=20)
        if resp4k.status_code == 200:
            embed4k = resp4k.json().get("embed_url", "")
            mid4k = EMBED_ID_RE.search(embed4k)
            if mid4k and valid_movie_id(mid4k.group(1)):
                movie_id_4k = mid4k.group(1)
        return {"movie_id": movie_id, "movie_id_4k": movie_id_4k}
    except Exception as e:
        print(f"    resolve_episode_stream error: {e}")
        return {"movie_id": "", "movie_id_4k": ""}


def normalize_imdb_id(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return value if value.startswith("tt") else "tt" + value.replace("tt", "", 1)


def resolve_series_episodes(public_session, auth_session, page_url: str, khd_id: str, imdb_id: str = "", resolve_streams: bool = False) -> list[dict]:
    episodes = scrape_series_episodes(public_session, page_url)
    public_id = normalize_imdb_id(imdb_id) or khd_id
    for ep in episodes:
        khd_episode_id = f"{khd_id}:{ep['season']}:{ep['episode']}"
        ep["id"] = f"{public_id}:{ep['season']}:{ep['episode']}"
        ep["khd_id"] = khd_episode_id
        if resolve_streams and auth_session:
            streams = resolve_episode_stream(auth_session, ep)
            ep["movie_id"] = streams["movie_id"]
            ep["movie_id_4k"] = streams["movie_id_4k"]
            time.sleep(PAGE_DELAY)
    return episodes


def resolve_free_series_episodes(public_session, auth_session, page_url: str, khd_id: str, imdb_id: str = "") -> list[dict]:
    return resolve_series_episodes(public_session, auth_session, page_url, khd_id, imdb_id=imdb_id, resolve_streams=True)

def update_series_episode_ids(entry: dict) -> None:
    if entry.get("type") != "series":
        return
    public_id = normalize_imdb_id(entry.get("imdb_id", "")) or entry.get("khd_id", "")
    khd_id = entry.get("khd_id", "")
    if not public_id or not khd_id:
        return
    for ep in entry.get("episodes", []) or []:
        season = ep.get("season") or 1
        episode = ep.get("episode") or 1
        ep["khd_id"] = ep.get("khd_id") or f"{khd_id}:{season}:{episode}"
        ep["id"] = f"{public_id}:{season}:{episode}"


def tmdb_metadata_mismatch(entry: dict) -> bool:
    source_tokens = text_tokens(entry.get("overview", ""))
    tmdb_tokens = text_tokens(entry.get("overview_en", "")) or text_tokens(entry.get("tmdb_overview", ""))
    if len(source_tokens) < 5 or len(tmdb_tokens) < 5:
        return False
    overlap = len(source_tokens & tmdb_tokens) / max(1, len(source_tokens))
    return overlap < 0.15


def apply_tmdb_metadata(entry: dict, tmdb: dict) -> None:
    field_map = {
        "title_english": "title_english",
        "year": "year",
        "tmdb_id": "tmdb_id",
        "imdb_id": "imdb_id",
        "tmdb_poster": "tmdb_poster",
        "backdrop": "backdrop",
        "genres": "genres",
        "overview_en": "overview",
        "imdb_rating": "imdb_rating",
        "runtime": "runtime",
    }
    for entry_key, tmdb_key in field_map.items():
        value = tmdb.get(tmdb_key)
        if value:
            entry[entry_key] = value



def resolve_free_stream(auth_session, page_url: str, kind: str) -> dict:
    """Resolve movie_id for a free item using cookies."""
    if not auth_session:
        return {"movie_id": "", "movie_id_4k": ""}
    try:
        r = auth_session.get(page_url, timeout=20)
        m = POSTID_RE.search(r.text)
        if not m:
            return {"movie_id": "", "movie_id_4k": ""}
        post_id = m.group(1)
        media_type = "tv" if kind == "series" else "movie"
        payload = {
            "action": "doo_player_ajax",
            "post": post_id,
            "nume": "1",
            "type": media_type,
        }
        resp = auth_session.post(AJAX_URL, data=payload,
                                 headers={"Referer": page_url}, timeout=20)
        if resp.status_code != 200:
            return {"movie_id": "", "movie_id_4k": ""}
        embed = resp.json().get("embed_url", "")
        mid = EMBED_ID_RE.search(embed)
        movie_id = mid.group(1) if mid and valid_movie_id(mid.group(1)) else ""

        # Check 4K
        movie_id_4k = ""
        has_4k = "data-nume=\'2\'" in r.text or 'data-nume="2"' in r.text
        if has_4k and movie_id:
            payload["nume"] = "2"
            resp4k = auth_session.post(AJAX_URL, data=payload,
                                       headers={"Referer": page_url}, timeout=20)
            if resp4k.status_code == 200:
                embed4k = resp4k.json().get("embed_url", "")
                mid4k = EMBED_ID_RE.search(embed4k)
                if mid4k and valid_movie_id(mid4k.group(1)):
                    movie_id_4k = mid4k.group(1)

        return {"movie_id": movie_id, "movie_id_4k": movie_id_4k}
    except Exception as e:
        print(f"    resolve_free_stream error: {e}")
        return {"movie_id": "", "movie_id_4k": ""}


def get_free_slugs(session: requests.Session) -> set:
    """Scrape all slugs from the free genre pages."""
    free_slugs = set()
    page = 1
    while True:
        url = FREE_GENRE_URL.format(page)
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 404:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.find_all("article")
            if not articles:
                break
            for art in articles:
                h3 = art.find("h3")
                if not h3:
                    continue
                link = h3.find("a", href=True)
                if not link:
                    continue
                slug = slug_from_url(link["href"])
                free_slugs.add(slug)
            page += 1
            time.sleep(PAGE_DELAY)
        except Exception as e:
            print(f"  Error scraping free page {page}: {e}")
            break
    print(f"✓ Found {len(free_slugs)} free slugs")
    return free_slugs


def main():
    session = make_session()
    cache = load_cache()
    previous_count = existing_catalog_count()
    all_items = []

    print("\n→ Scraping free genre slugs...")
    free_slugs = get_free_slugs(session)
    auth_session = make_auth_session() if RESOLVE_FREE_STREAMS else None
    if auth_session:
        print("✓ Auth session ready for free stream resolution")
    elif not RESOLVE_FREE_STREAMS:
        print("✓ Public metadata mode — free stream resolution disabled")
    else:
        print("⚠ No cookies found — free streams won't be resolved")

    for source in SOURCES:
        kind      = source["kind"]
        stype     = source["type"]
        base_url  = source["base_url"]
        media_type = "tv" if stype == "series" else "movie"

        print(f"\n{'='*60}")
        print(f"Scraping {kind}s...")
        print("=" * 60)

        page = 1
        while True:
            url = base_url.format(page)
            print(f"  Page {page}: {url}")
            items = scrape_listing_page(session, url)

            if items is None:
                print(f"  No more pages after page {page - 1}")
                break
            if not items:
                page += 1
                continue

            print(f"  Found {len(items)} items")
            all_items.extend([(item, stype, media_type) for item in items])
            page += 1
            time.sleep(PAGE_DELAY)

    print(f"\n{'='*60}")
    print(f"Total scraped: {len(all_items)} items")
    if (not ALLOW_LARGE_SHRINK
            and not catalog_size_is_safe(len(all_items), previous_count)):
        raise RuntimeError(
            f"Refusing incomplete catalog: listing returned {len(all_items)} items, "
            f"previous catalog has {previous_count}. Set "
            "FULL_CATALOG_ALLOW_LARGE_SHRINK=1 only for an intentional removal."
        )
    print(f"Enriching with TMDB metadata...")
    print("=" * 60)

    catalog = []
    for i, (item, stype, media_type) in enumerate(all_items, 1):
        slug       = item["slug"]
        title_khmer = item["title_khmer"]
        cache_key  = hashlib.md5(slug.encode()).hexdigest()

        if cache_key in cache and cache_entry_is_current(cache[cache_key], item, stype):
            entry = dict(cache[cache_key])
            entry.update({
                "slug": slug,
                "type": stype,
                "title_khmer": title_khmer,
                "page_url": item["page_url"],
            })
            if valid_poster_url(item.get("poster")):
                entry["poster"] = item["poster"]
            elif not valid_poster_url(entry.get("poster")):
                entry["poster"] = ""
            if item.get("rating"):
                entry["imdb_rating"] = item["rating"]
            entry["is_free"] = slug in free_slugs or "ឥតគិតថ្លៃ" in title_khmer
            apply_manual_metadata(entry)
            if stype == "series":
                update_series_episode_ids(entry)
            if not entry.get("poster"):
                print(f"  [{i:>3}/{len(all_items)}] refreshing poster {title_khmer[:40]}")
                details = scrape_page_details(session, item["page_url"])
                if details.get("status_code") == 404:
                    print(f"    skipping broken listing (detail page is 404): {item['page_url']}")
                    cache.pop(cache_key, None)
                    continue
                if details.get("poster"):
                    entry["poster"] = details["poster"]
                if details.get("overview") and not entry.get("overview"):
                    entry["overview"] = details["overview"]
                if details.get("year") and not entry.get("year"):
                    entry["year"] = details["year"]
                if details.get("runtime") and not entry.get("runtime"):
                    entry["runtime"] = details["runtime"]
                cache[cache_key] = entry
                time.sleep(PAGE_DELAY)
            if stype == "series" and not entry.get("episodes"):
                action = "scraping series episodes"
                print(f"  [{i:>3}/{len(all_items)}] {action} {title_khmer[:40]}")
                entry["episodes"] = resolve_series_episodes(
                    session, auth_session, item["page_url"], entry["khd_id"],
                    imdb_id=entry.get("imdb_id", ""),
                    resolve_streams=entry["is_free"] and RESOLVE_FREE_STREAMS,
                )
                entry["movie_id"] = ""
                entry["movie_id_4k"] = ""
                cache[cache_key] = entry
            elif RESOLVE_FREE_STREAMS and entry["is_free"] and stype != "series" and (not valid_movie_id(entry.get("movie_id"))) and auth_session:
                print(f"  [{i:>3}/{len(all_items)}] resolving free stream {title_khmer[:40]}")
                streams = resolve_free_stream(auth_session, item["page_url"], stype)
                entry["movie_id"] = streams["movie_id"]
                entry["movie_id_4k"] = streams["movie_id_4k"]
                cache[cache_key] = entry
                time.sleep(PAGE_DELAY)
            else:
                print(f"  [{i:>3}/{len(all_items)}] reused  {title_khmer[:55]}")
            cache[cache_key] = entry
            catalog.append({k: v for k, v in entry.items() if not k.startswith("_")})
            continue

        # Extract English title for TMDB search
        title_english = extract_english_from_khmer_title(title_khmer)

        print(f"  [{i:>3}/{len(all_items)}] fetching {title_khmer[:55]}")

        # Scrape detail-page fields first so TMDB matching can disambiguate common titles.
        details = scrape_page_details(session, item["page_url"])
        if details.get("status_code") == 404:
            print(f"    skipping broken listing (detail page is 404): {item['page_url']}")
            cache.pop(cache_key, None)
            continue
        khmer_overview = details.get("overview", "")
        original_title = details.get("original_title", "")
        search_title = original_title or title_english or title_khmer
        time.sleep(PAGE_DELAY)

        tmdb = fetch_tmdb(search_title, details.get("year", ""), media_type, overview_hint=khmer_overview)

        # Build khd_id from slug
        khd_id = f"khdcat_{slug}"

        # Resolve stream for free items
        movie_id = ""
        movie_id_4k = ""
        episodes = []
        is_free_item = slug in free_slugs or "ឥតគិតថ្លៃ" in title_khmer
        if stype == "series":
            action = "scraping series episodes"
            print(f"    → {action} for {slug}")
            episodes = resolve_series_episodes(
                session, auth_session, item["page_url"], khd_id,
                imdb_id=tmdb.get("imdb_id", ""),
                resolve_streams=is_free_item and RESOLVE_FREE_STREAMS,
            )
        elif RESOLVE_FREE_STREAMS and is_free_item and auth_session:
            print(f"    → resolving free stream for {slug}")
            streams = resolve_free_stream(auth_session, item["page_url"], stype)
            movie_id = streams["movie_id"]
            movie_id_4k = streams["movie_id_4k"]
            time.sleep(PAGE_DELAY)

        entry = {
            "khd_id":        khd_id,
            "slug":          slug,
            "is_free":       is_free_item,
            "movie_id":      movie_id,
            "movie_id_4k":   movie_id_4k,
            "episodes":      episodes,
            "type":          stype,
            "title_khmer":   title_khmer,
            "title_english": tmdb.get("title_english") or original_title or title_english or title_khmer,
            "original_title": original_title,
            "year":          tmdb.get("year") or details.get("year", ""),
            "poster":        (item.get("poster") if valid_poster_url(item.get("poster"))
                              else details.get("poster") or tmdb.get("tmdb_poster", "")),
            "tmdb_poster":   tmdb.get("tmdb_poster", ""),
            "backdrop":      tmdb.get("backdrop", ""),
            "genres":        tmdb.get("genres", []),
            "overview":      khmer_overview or tmdb.get("overview", ""),
            "overview_en":   tmdb.get("overview", ""),
            "imdb_id":       tmdb.get("imdb_id", ""),
            "tmdb_id":       tmdb.get("tmdb_id", ""),
            "imdb_rating":   item.get("rating") or tmdb.get("imdb_rating", ""),
            "runtime":       tmdb.get("runtime") or details.get("runtime", ""),
            "page_url":      item["page_url"],
            "tmdb_match_score": tmdb.get("match_score", ""),
            "_cache_version": CACHE_VERSION,
            "_source_signature": source_signature(item, stype),
        }
        apply_manual_metadata(entry)
        update_series_episode_ids(entry)

        cache[cache_key] = entry
        catalog.append({k: v for k, v in entry.items() if not k.startswith("_")})
        time.sleep(PAGE_DELAY)

    save_cache(cache)

    write_json_atomic(OUTPUT_PATH, catalog)

    print(f"\n{'='*60}")
    print(f"✓ full_catalog.json written → {OUTPUT_PATH}")
    print(f"  Total  : {len(catalog)}")
    print(f"  Movies : {sum(1 for e in catalog if e['type'] == 'movie')}")
    print(f"  Series : {sum(1 for e in catalog if e['type'] == 'series')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
