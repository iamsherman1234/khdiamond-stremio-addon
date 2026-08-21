#!/usr/bin/env python3
"""
user_scrape.py — Per-user scraper (no Google Sheet)
Reads cookies from $COOKIES_PATH
Paginates through all pages of $LIBRARY_URL (e.g. /my-account/, /my-account/page/2/, ...)
Writes to $USER_DIR/library_raw.json
"""
import sys
import os
import json
import time
import random
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
from bs4 import BeautifulSoup
from khdiamond_http import is_login_page, library_rows
from khdiamond_credentials import login_with_saved_credentials

LIBRARY_URL  = "https://khdiamond.net/my-account/"
COOKIES_PATH = Path(os.environ.get("COOKIES_PATH", "/root/khdiamond/cookies.txt"))
USER_DIR     = Path(os.environ.get("USER_DIR", "/root/khdiamond"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
      "Gecko/20100101 Firefox/149.0")
MAX_RETRIES  = 3


def make_session() -> requests.Session:
    jar = MozillaCookieJar(str(COOKIES_PATH))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = jar
    s.headers.update({"User-Agent": UA, "Referer": "https://khdiamond.net/"})
    return s


def fetch_library_page(session: requests.Session, page: int = 1):
    url = f"https://khdiamond.net/my-account/page/{page}/" if page > 1 else LIBRARY_URL
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 429:
                wait = 5 * (attempt + 1) + random.uniform(0, 1)
                if attempt < MAX_RETRIES:
                    print(f"  (429 — waiting {wait:.1f}s before retry {attempt+1}/{MAX_RETRIES})")
                    time.sleep(wait)
                    continue
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                time.sleep(3)
                continue
            raise exc


def main():
    if not COOKIES_PATH.exists():
        sys.exit(f"❌ {COOKIES_PATH} missing — upload fresh cookies first.")

    session = make_session()

    page = 1
    all_rows = []
    seen = set()

    while True:
        target_url = LIBRARY_URL if page == 1 else f"{LIBRARY_URL}page/{page}/"
        print(f"→ GET {target_url}")
        try:
            r = fetch_library_page(session, page)
        except Exception as e:
            print(f"  Fetch library error on page {page}: {e}")
            if page == 1:
                print("  Attempting automatic login renewal...")
                ok, msg = login_with_saved_credentials(USER_DIR, COOKIES_PATH)
                if ok:
                    session = make_session()
                    r = fetch_library_page(session, page)
                else:
                    raise e
            else:
                break

        if r is None:
            print(f"  Page {page} returned 404 (end of library)")
            break

        html = r.text
        print(f"  ← {len(html):,} bytes")
        if is_login_page(r):
            if page == 1:
                print("  Session expired — attempting encrypted automatic login...")
                ok, message = login_with_saved_credentials(USER_DIR, COOKIES_PATH)
                if ok:
                    session = make_session()
                    r = fetch_library_page(session, page)
                    html = r.text
                    print(f"  ✓ Automatic login succeeded ({len(html):,} bytes)")
                else:
                    print(f"  Automatic login unavailable: {message}")

            if is_login_page(r):
                expired_path = USER_DIR / "expired.txt"
                expired_path.write_text("Cookies expired")
                sys.exit("❌ Got login page — cookies expired.")

        (USER_DIR / "expired.txt").unlink(missing_ok=True)

        rows = library_rows(html, r.url)
        new_rows = [row for row in rows if (row["kind"], row["slug"]) not in seen]
        if not new_rows:
            print(f"  No more items on page {page}")
            break

        for row in new_rows:
            seen.add((row["kind"], row["slug"]))
            all_rows.append(row)

        print(f"  Found {len(new_rows)} new items (total so far: {len(all_rows)})")
        page += 1
        time.sleep(0.4)

    if not all_rows:
        sys.exit("❌ Zero items parsed — check cookies or site structure.")

    print(f"\n✓ Extracted {len(all_rows)} total unique items across {page - 1} page(s)")
    by_kind = {}
    for r in all_rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    for k, v in by_kind.items():
        print(f"  {k}: {v}")

    out_path = USER_DIR / "library_raw.json"
    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2))
    os.replace(tmp_path, out_path)
    print(f"✓ Wrote {len(all_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
