#!/usr/bin/env python3
"""
user_scrape.py — Per-user scraper (no Google Sheet)
Reads cookies from $COOKIES_PATH
Writes to $USER_DIR/library_raw.json
"""
import sys
import os
import json
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


def fetch_library():
    jar = MozillaCookieJar(str(COOKIES_PATH))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = jar
    s.headers.update({"User-Agent": UA, "Referer": "https://khdiamond.net/"})

    response = s.get(LIBRARY_URL, timeout=30)
    response.raise_for_status()
    return response


def main():
    if not COOKIES_PATH.exists():
        sys.exit(f"❌ {COOKIES_PATH} missing — upload fresh cookies first.")

    print(f"→ GET {LIBRARY_URL}")
    r = fetch_library()
    html = r.text
    print(f"  ← {len(html):,} bytes")
    if is_login_page(r):
        print("  Session expired — attempting encrypted automatic login...")
        ok, message = login_with_saved_credentials(USER_DIR, COOKIES_PATH)
        if ok:
            r = fetch_library()
            html = r.text
            print(f"  ✓ Automatic login succeeded ({len(html):,} bytes)")
        else:
            print(f"  Automatic login unavailable: {message}")

    if is_login_page(r):
        # Write expired marker for web UI
        expired_path = USER_DIR / "expired.txt"
        expired_path.write_text("Cookies expired")
        sys.exit("❌ Got login page — cookies expired.")

    (USER_DIR / "expired.txt").unlink(missing_ok=True)

    rows = library_rows(html, r.url)

    if not rows:
        sys.exit("❌ Zero items parsed — check cookies or site structure.")

    print(f"\n✓ Extracted {len(rows)} items")
    by_kind = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    for k, v in by_kind.items():
        print(f"  {k}: {v}")

    out_path = USER_DIR / "library_raw.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"✓ Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
