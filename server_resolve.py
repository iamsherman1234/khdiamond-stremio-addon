#!/usr/bin/env python3
"""
server_resolve.py — Resolve movie_id + movie_id_4k → 'list' sheet
Server version of resolve_all.py (no Colab dependency).

Reads cookies from /root/khdiamond/cookies.txt
Auth via GDRIVE_SERVICE_ACCOUNT env var (service account JSON)
"""
import re
import sys
import time
import random
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
import pandas as pd
from bs4 import BeautifulSoup
from khdiamond_http import (extract_media_id, extract_nonce, extract_post_id,
                            response_embed_url)

sys.path.insert(0, "/root/khdiamond")
from drive_manager import get_gspread_client

SPREADSHEET_ID = "1gAjrURaRX3ce1gf-KyUw2UOlwYX3aEYc_7YnQD6T-5g"
COOKIES_PATH   = Path("/root/khdiamond/cookies.txt")
AJAX_URL       = "https://khdiamond.net/wp-admin/admin-ajax.php"
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


def call_player_ajax(session, post_id: str, kind: str,
                     referer: str, nume: str = "1") -> dict:
    out = {"status": "", "movie_id": "", "embed_url": ""}
    cache = getattr(session, "_khdiamond_page_cache", {})
    page_html = cache.get(referer, "")
    if not page_html:
        try:
            page = session.get(referer, timeout=20)
            page.raise_for_status()
            page_html = page.text
            cache[referer] = page_html
            session._khdiamond_page_cache = cache
        except requests.RequestException as exc:
            out["status"] = f"page_err:{type(exc).__name__}"
            return out
    nonce = extract_nonce(page_html)
    if not nonce:
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
            r = session.post(AJAX_URL, data=payload,
                             headers=headers, timeout=20)
        except requests.Timeout:
            out["status"] = "timeout"; return out
        except Exception as e:
            out["status"] = f"err:{type(e).__name__}"; return out

        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            wait = int(ra) if (ra and ra.isdigit()) else (
                BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1))
            if attempt < MAX_RETRIES:
                print(f"      (429 — sleeping {wait:.1f}s)")
                time.sleep(wait); continue
            out["status"] = "http_429_giveup"; return out

        if r.status_code != 200:
            out["status"] = f"http_{r.status_code}"; return out

        embed = response_embed_url(r)
        out["embed_url"] = embed
        movie_id = extract_media_id(embed)
        if movie_id:
            out["movie_id"] = movie_id
            out["status"] = "ok"
        else:
            out["status"] = "player_rejected" if r.text.strip() == "0" else "no_id_in_embed"
        return out

    out["status"] = "http_429_giveup"
    return out


def fetch_episode_list(session, series_slug: str, series_title: str,
                       series_url: str) -> list[dict]:
    print(f"  fetching series page → {series_url}")
    r = session.get(series_url, timeout=30,
                    headers={"Referer": "https://khdiamond.net/"})
    if r.status_code != 200:
        print(f"    HTTP {r.status_code} — skipping series")
        return []
    html = r.text
    ep_urls = sorted(set(EP_LINK_RE.findall(html)))
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
    for ep_url in ep_urls:
        season, ep_num, ep_title = ep_meta.get(ep_url, ("", "", ""))
        try:
            er = session.get(ep_url, timeout=30,
                             headers={"Referer": series_url})
        except Exception as e:
            print(f"    ep fetch err {ep_url}: {e}")
            time.sleep(FETCH_DELAY); continue
        if er.status_code != 200:
            print(f"    ep {ep_url} HTTP {er.status_code}")
            time.sleep(FETCH_DELAY); continue

        m = POSTID_RE.search(er.text)
        if not m:
            print(f"    no postid in {ep_url}")
            time.sleep(FETCH_DELAY); continue
        post_id = m.group(1)

        se_tag = ""
        if season and ep_num:
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
        })
        time.sleep(FETCH_DELAY)

    return episodes


def check_4k_option(session, page_url: str) -> bool:
    try:
        r = session.get(page_url, timeout=20)
        return "data-nume='2'" in r.text or 'data-nume="2"' in r.text
    except Exception:
        return False


def main():
    if not COOKIES_PATH.exists():
        sys.exit(f"❌ {COOKIES_PATH} missing — upload fresh cookies first.")

    print("→ Authenticating to Sheets...")
    gc = get_gspread_client()
    ss = gc.open_by_key(SPREADSHEET_ID)

    src_rows = ss.worksheet("library_raw").get_all_records()
    print(f"✓ Read {len(src_rows)} rows from 'library_raw'\n")

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
    print(f"→ Resolving {len(worklist)} items (movies + episodes)\n")

    # Resolve each item
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
            out.update({"status": "bad_article_id",
                        "movie_id": "", "embed_url": ""})
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

    # Retry pass
    failed_idx = [i for i, r in enumerate(results)
                  if r["status"].startswith(("http_429", "err", "timeout"))]
    if failed_idx:
        print(f"\n→ Retry pass for {len(failed_idx)} failed items...")
        time.sleep(5)
        for i in failed_idx:
            row = worklist[i]
            art = str(row.get("article_id", "")).lstrip("p").strip()
            if not art.isdigit():
                continue
            referer = row.get("page_url") or "https://khdiamond.net/"
            res = call_player_ajax(
                session, art,
                kind="tvshows" if row.get("kind") == "episode" else "movies",
                referer=referer,
            )
            results[i].update(res)
            mark = "✓" if res["status"] == "ok" else "✗"
            print(f"  retry → {mark} {res['status']:17s} "
                  f"{results[i].get('title','')[:55]:55s} "
                  f"→ {res.get('movie_id', '')}")
            time.sleep(RETRY_DELAY)

    elapsed = time.time() - t0
    df = pd.DataFrame(results)
    if "movie_id_4k" not in df.columns:
        df["movie_id_4k"] = ""

    print("\n" + "═" * 60)
    print(f"Resolved in {elapsed:.1f}s")
    print(df["status"].value_counts().to_string())
    has_4k_count = (df["movie_id_4k"] != "").sum()
    print(f"Movies with 4K: {has_4k_count}")
    print("═" * 60)

    # Write debug table
    try:
        ws = ss.worksheet("library_resolved"); ws.clear()
    except Exception:
        ws = ss.add_worksheet(title="library_resolved", rows=300, cols=11)
    for col in ("slug", "title", "kind", "year", "page_url",
                "article_id", "series", "movie_id", "movie_id_4k",
                "embed_url", "status"):
        if col not in df.columns:
            df[col] = ""
    df = df[["slug", "title", "kind", "year", "page_url",
             "article_id", "series", "movie_id", "movie_id_4k",
             "embed_url", "status"]]
    df = df.fillna("").replace([float("inf"), float("-inf")], "")
    ws.update([df.columns.tolist()] + df.astype(str).values.tolist())
    print(f"\n✓ Wrote debug table → 'library_resolved' ({len(df)} rows)")

    # Write list tab
    ok = df[df["status"] == "ok"][["movie_id", "movie_id_4k", "title"]].copy()
    ok = ok.fillna("")
    try:
        list_ws = ss.worksheet("list"); list_ws.clear()
    except Exception:
        list_ws = ss.add_worksheet(title="list", rows=300, cols=3)
    list_ws.update([ok.columns.tolist()] + ok.astype(str).values.tolist())
    print(f"✓ Wrote {len(ok)} rows → 'list' (movie_id, movie_id_4k, title)")

    failed = df[~df["status"].isin(["ok"])]
    if not failed.empty:
        print(f"\n⚠ {len(failed)} failed — re-run or inspect 'library_resolved'")


if __name__ == "__main__":
    main()
