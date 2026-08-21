#!/usr/bin/env python3
"""
user_resolve.py — Per-user resolver (no Google Sheet)
Reads $USER_DIR/library_raw.json
Writes $USER_DIR/list.json
"""
import re
import sys
import os
import json
import time
import random
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
from bs4 import BeautifulSoup
from khdiamond_http import (extract_media_id, extract_nonce, extract_post_id,
                            response_embed_url)
from khdiamond_credentials import load_credentials, login_with_saved_credentials

COOKIES_PATH = Path(os.environ.get("COOKIES_PATH", "/root/khdiamond/cookies.txt"))
USER_DIR     = Path(os.environ.get("USER_DIR", "/root/khdiamond"))
AJAX_URL     = "https://khdiamond.net/wp-admin/admin-ajax.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
      "Gecko/20100101 Firefox/149.0")

BASE_DELAY   = 0.4
FETCH_DELAY  = 0.3
RETRY_DELAY  = 2.0
MAX_RETRIES  = 4
BACKOFF_BASE = 3

POSTID_RE   = re.compile(r"postid-(\d+)")
EP_LINK_RE  = re.compile(r'href=["\'](https?://khdiamond\.net/episodes/[^"\']+/)["\']')
NUM_RE      = re.compile(r"(\d+)\s*-\s*(\d+)")


def make_session() -> requests.Session:
    jar = MozillaCookieJar(str(COOKIES_PATH))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = jar
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://khdiamond.net/",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://khdiamond.net",
    })
    return s


def renew_session_if_possible(session: requests.Session) -> bool:
    if not load_credentials(USER_DIR):
        return False
    print("    (Attempting automatic session renewal via saved credentials...)")
    ok, msg = login_with_saved_credentials(USER_DIR, COOKIES_PATH)
    if ok:
        jar = MozillaCookieJar(str(COOKIES_PATH))
        jar.load(ignore_discard=True, ignore_expires=True)
        session.cookies = jar
        if hasattr(session, "_khdiamond_page_cache"):
            session._khdiamond_page_cache.clear()
        print("    (✓ Automatic session renewal succeeded)")
        return True
    print(f"    (Session renewal failed: {msg})")
    return False


def call_player_ajax(session, post_id, kind, referer, nume="1", allow_renew=True):
    out = {"status": "", "movie_id": "", "embed_url": ""}
    cache = getattr(session, "_khdiamond_page_cache", {})
    page_html = cache.get(referer, "")
    if not page_html:
        for p_attempt in range(MAX_RETRIES + 1):
            try:
                page = session.get(referer, timeout=20)
                if page.status_code == 429:
                    wait = BACKOFF_BASE * (2 ** p_attempt) + random.uniform(0, 1)
                    if p_attempt < MAX_RETRIES:
                        print(f"      (Page 429 — sleeping {wait:.1f}s)")
                        time.sleep(wait)
                        continue
                page.raise_for_status()
                page_html = page.text
                cache[referer] = page_html
                session._khdiamond_page_cache = cache
                break
            except requests.RequestException as exc:
                if p_attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                out["status"] = f"page_err:{type(exc).__name__}"
                return out

    nonce = extract_nonce(page_html)
    if not nonce:
        if allow_renew and renew_session_if_possible(session):
            return call_player_ajax(session, post_id, kind, referer, nume=nume, allow_renew=False)
        out["status"] = "nonce_missing"
        return out

    payload = {
        "action": "doo_player_ajax",
        "post":   post_id,
        "nume":   nume,
        "type":   "tv" if kind == "tvshows" else "movie",
        "nonce":  nonce,
    }
    headers = {"Referer": referer}

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = session.post(AJAX_URL, data=payload, headers=headers, timeout=20)
        except requests.Timeout:
            out["status"] = "timeout"
            return out
        except Exception as e:
            out["status"] = f"err:{type(e).__name__}"
            return out

        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            wait = int(ra) if (ra and ra.isdigit()) else (
                BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1))
            if attempt < MAX_RETRIES:
                print(f"      (429 — sleeping {wait:.1f}s)")
                time.sleep(wait)
                continue
            out["status"] = "http_429_giveup"
            return out

        if r.status_code in (400, 401, 403):
            if allow_renew and renew_session_if_possible(session):
                return call_player_ajax(session, post_id, kind, referer, nume=nume, allow_renew=False)
            out["status"] = f"http_{r.status_code}"
            return out

        if r.status_code != 200:
            out["status"] = f"http_{r.status_code}"
            return out

        embed = response_embed_url(r)
        out["embed_url"] = embed
        movie_id = extract_media_id(embed)
        if movie_id:
            out["movie_id"] = movie_id
            out["status"] = "ok"
        else:
            if r.text.strip() == "0" and allow_renew and renew_session_if_possible(session):
                return call_player_ajax(session, post_id, kind, referer, nume=nume, allow_renew=False)
            out["status"] = "player_rejected" if r.text.strip() == "0" else "no_id_in_embed"
        return out

    out["status"] = "http_429_giveup"
    return out


def fetch_episode_list(session, series_slug, series_title, series_url):
    print(f"  fetching series page → {series_url}")
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = session.get(series_url, timeout=30,
                            headers={"Referer": "https://khdiamond.net/"})
            if r.status_code == 429:
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                if attempt < MAX_RETRIES:
                    print(f"    (Series 429 — sleeping {wait:.1f}s)")
                    time.sleep(wait)
                    continue
            if r.status_code != 200:
                print(f"    HTTP {r.status_code} — skipping")
                return []
            break
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            print(f"    Series fetch err {series_url}: {e}")
            return []

    html = r.text
    ep_urls = list(dict.fromkeys(EP_LINK_RE.findall(html)))
    print(f"    found {len(ep_urls)} episodes")
    time.sleep(FETCH_DELAY)

    soup = BeautifulSoup(html, "html.parser")
    ep_meta = {}
    for li in soup.select("ul.episodios > li"):
        a = li.select_one("div.episodiotitle a[href]")
        if not a:
            continue
        ep_href = a["href"]
        ep_title = a.get_text(strip=True)
        num_el = li.select_one("div.numerando")
        season = episode = ""
        if num_el and (m := NUM_RE.search(num_el.get_text())):
            season, episode = m.group(1), m.group(2)
        ep_meta[ep_href] = (season, episode, ep_title)

    episodes = []
    for i, ep_url in enumerate(ep_urls, 1):
        season, ep_num, ep_title = ep_meta.get(ep_url, ("", "", ""))
        if not ep_num:
            ep_num = str(i)
        if not season:
            season = "1"
        if not ep_title:
            ep_title = f"ភាគទី {i}"

        er = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                er = session.get(ep_url, timeout=30,
                                 headers={"Referer": series_url})
                if er.status_code == 429:
                    wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1)
                    if attempt < MAX_RETRIES:
                        time.sleep(wait)
                        continue
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                print(f"    ep fetch err {ep_url}: {e}")
                er = None

        if not er or er.status_code != 200:
            time.sleep(FETCH_DELAY)
            continue

        m = POSTID_RE.search(er.text)
        if not m:
            time.sleep(FETCH_DELAY)
            continue
        post_id = m.group(1)

        se_tag = f" — S{int(season):02d}E{int(ep_num):02d}"
        full_title = f"{series_title}{se_tag}"
        if ep_title and ep_title != full_title:
            full_title = f"{full_title} — {ep_title}"

        ep_slug = ep_url.rstrip("/").rsplit("/", 1)[-1]
        episodes.append({
            "slug":       ep_slug,
            "title":      full_title,
            "kind":       "episode",
            "year":       "",
            "page_url":   ep_url,
            "article_id": f"p{post_id}",
            "series":     series_slug,
            "season":     int(season),
            "episode":    int(ep_num),
        })
        time.sleep(FETCH_DELAY)

    return episodes


def check_4k_option(session, page_url):
    try:
        r = session.get(page_url, timeout=20)
        return "data-nume='2'" in r.text or 'data-nume="2"' in r.text
    except Exception:
        return False


def main():
    if not COOKIES_PATH.exists():
        sys.exit(f"❌ {COOKIES_PATH} missing.")

    raw_path = USER_DIR / "library_raw.json"
    if not raw_path.exists():
        sys.exit(f"❌ {raw_path} missing — run user_scrape.py first.")

    src_rows = json.loads(raw_path.read_text())
    print(f"✓ Read {len(src_rows)} rows from library_raw.json\n")

    session = make_session()

    # Expand tvshows into episodes
    expanded = []
    tvshows = [r for r in src_rows if r.get("kind") == "tvshows"]
    print(f"→ Expanding {len(tvshows)} tvshow(s) into episodes...")
    for r in tvshows:
        eps = fetch_episode_list(
            session,
            series_slug=r["slug"],
            series_title=r["title"],
            series_url=r["page_url"],
        )
        expanded.extend(eps)
    print(f"✓ {len(expanded)} total episodes collected\n")

    worklist = [r for r in src_rows if r.get("kind") == "movies"] + expanded
    print(f"→ Resolving {len(worklist)} items\n")

    results = []
    t0 = time.time()
    for i, row in enumerate(worklist, 1):
        art = str(row.get("article_id", "")).lstrip("p").strip()
        out = dict(row)
        out["movie_id_4k"] = ""

        if not art.isdigit() and row.get("page_url"):
            try:
                page = session.get(row["page_url"], timeout=20)
                page.raise_for_status()
                art = extract_post_id(page.text)
                cache = getattr(session, "_khdiamond_page_cache", {})
                cache[row["page_url"]] = page.text
                session._khdiamond_page_cache = cache
            except requests.RequestException:
                pass

        if not art.isdigit():
            out.update({"status": "bad_article_id", "movie_id": "", "embed_url": ""})
        else:
            referer = row.get("page_url") or "https://khdiamond.net/"
            kind = "tvshows" if row.get("kind") == "episode" else "movies"

            res = call_player_ajax(session, art, kind=kind, referer=referer, nume="1")
            out.update(res)

            if out["status"] == "ok" and kind == "movies" and row.get("page_url"):
                has_4k = check_4k_option(session, row["page_url"])
                time.sleep(FETCH_DELAY)
                if has_4k:
                    res_4k = call_player_ajax(session, art, kind=kind,
                                              referer=referer, nume="2")
                    if res_4k["status"] == "ok":
                        out["movie_id_4k"] = res_4k["movie_id"]
                        time.sleep(BASE_DELAY)

        results.append(out)
        mark = "✓" if out["status"] == "ok" else "✗"
        title_short = (out.get("title") or "")[:50]
        k4 = f" 4K:{out['movie_id_4k']}" if out.get("movie_id_4k") else ""
        print(f"  [{i:>3}/{len(worklist)}] {mark} {out['status']:17s} "
              f"{title_short:50s} → {out.get('movie_id', '')}{k4}")

        if out["status"] not in ("bad_article_id",):
            time.sleep(BASE_DELAY)

    # Retry pass for all failed items
    failed_idx = [i for i, r in enumerate(results) if r["status"] != "ok"]
    if failed_idx:
        print(f"\n→ Retry pass for {len(failed_idx)} failed items...")
        renew_session_if_possible(session)
        time.sleep(3)
        for i in failed_idx:
            row = worklist[i]
            art = str(row.get("article_id", "")).lstrip("p").strip()
            if not art.isdigit():
                continue
            referer = row.get("page_url") or "https://khdiamond.net/"
            kind = "tvshows" if row.get("kind") == "episode" else "movies"
            res = call_player_ajax(
                session, art,
                kind=kind,
                referer=referer,
                allow_renew=True,
            )
            results[i].update(res)
            if res["status"] == "ok" and kind == "movies" and row.get("page_url") and not results[i].get("movie_id_4k"):
                if check_4k_option(session, row["page_url"]):
                    res_4k = call_player_ajax(session, art, kind=kind, referer=referer, nume="2")
                    if res_4k["status"] == "ok":
                        results[i]["movie_id_4k"] = res_4k["movie_id"]
            mark = "✓" if results[i]["status"] == "ok" else "✗"
            k4 = f" 4K:{results[i]['movie_id_4k']}" if results[i].get("movie_id_4k") else ""
            print(f"  retry → {mark} {results[i]['status']:17s} "
                  f"{results[i].get('title','')[:50]:50s} "
                  f"→ {results[i].get('movie_id', '')}{k4}")
            time.sleep(RETRY_DELAY)

    elapsed = time.time() - t0
    ok = [r for r in results if r["status"] == "ok"]
    has_4k = sum(1 for r in ok if r.get("movie_id_4k"))

    print(f"\n{'═'*60}")
    print(f"Resolved in {elapsed:.1f}s — {len(ok)}/{len(results)} ok, {has_4k} with 4K")
    print("═" * 60)

    out_path = USER_DIR / "list.json"
    allow_shrink = os.environ.get("ALLOW_LARGE_SHRINK", "0").lower() in ("1", "true", "yes")

    # Safety guards against wiping catalogs
    if len(worklist) > 0 and len(ok) == 0:
        sys.exit(f"❌ Refusing to overwrite {out_path}: 0 of {len(worklist)} items resolved. Preserving previous list.")

    if len(worklist) > 0 and len(ok) < len(worklist) * 0.4 and not allow_shrink:
        if out_path.exists():
            try:
                prev = json.loads(out_path.read_text())
                if len(prev) > len(ok):
                    sys.exit(
                        f"❌ Refusing degraded list: only {len(ok)}/{len(worklist)} items resolved, "
                        f"previous list had {len(prev)}. Preserving existing list. "
                        f"Set ALLOW_LARGE_SHRINK=1 to override."
                    )
            except Exception:
                pass

    # Write list.json atomically
    list_data = [{"movie_id": r["movie_id"], "movie_id_4k": r.get("movie_id_4k", ""),
                  "title": r["title"], "kind": r["kind"],
                  "year": r.get("year", ""), "page_url": r.get("page_url", ""),
                  "slug": r.get("slug", ""), "series": r.get("series", ""),
                  "season": r.get("season", 1), "episode": r.get("episode", 1)}
                 for r in ok]

    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(list_data, ensure_ascii=False, indent=2))
    os.replace(tmp_path, out_path)
    print(f"✓ Wrote {len(list_data)} rows to {out_path}")

    failed = [r for r in results if r["status"] != "ok"]
    if failed:
        print(f"⚠ {len(failed)} failed items")


if __name__ == "__main__":
    main()
