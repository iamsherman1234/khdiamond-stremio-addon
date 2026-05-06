#!/usr/bin/env python3
"""
user_scrape.py — Per-user scraper (no Google Sheet)
Reads cookies from $COOKIES_PATH
Writes to $USER_DIR/library_raw.json
"""
import re
import sys
import os
import json
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
from bs4 import BeautifulSoup

LIBRARY_URL  = "https://khdiamond.net/my-account/"
COOKIES_PATH = Path(os.environ.get("COOKIES_PATH", "/root/khdiamond/cookies.txt"))
USER_DIR     = Path(os.environ.get("USER_DIR", "/root/khdiamond"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) "
      "Gecko/20100101 Firefox/149.0")


def main():
    if not COOKIES_PATH.exists():
        sys.exit(f"❌ {COOKIES_PATH} missing — upload fresh cookies first.")

    jar = MozillaCookieJar(str(COOKIES_PATH))
    jar.load(ignore_discard=True, ignore_expires=True)
    s = requests.Session()
    s.cookies = jar
    s.headers.update({"User-Agent": UA, "Referer": "https://khdiamond.net/"})

    print(f"→ GET {LIBRARY_URL}")
    r = s.get(LIBRARY_URL, timeout=30)
    r.raise_for_status()
    html = r.text
    print(f"  ← {len(html):,} bytes")
    if len(html) < 20_000 or "<h1>Log in</h1>" in html:
        # Write expired marker for web UI
        expired_path = Path(os.environ.get("USER_DIR", "/root/khdiamond")) / "expired.txt"
        expired_path.write_text("Cookies expired")
        sys.exit("❌ Got login page — cookies expired.")

    soup = BeautifulSoup(html, "html.parser")
    path_re = re.compile(r"/(movies|tvshows|series|tvshow|episode)/([^/]+)/?")

    rows = []
    for art in soup.find_all("article"):
        h3 = art.find("h3")
        if not h3:
            continue
        link = h3.find("a", href=True)
        if not link:
            continue
        m = path_re.search(link["href"])
        if not m:
            continue
        kind, slug = m.group(1), m.group(2)

        year = ""
        data_div = art.find("div", class_="data")
        if data_div and (y := data_div.find("span")):
            year = y.get_text(strip=True)

        rows.append({
            "slug":       slug,
            "title":      link.get_text(strip=True),
            "kind":       kind,
            "year":       year,
            "page_url":   link["href"],
            "article_id": art.get("id", ""),
        })

    # Deduplicate
    seen = set()
    deduped = []
    for row in rows:
        key = (row["slug"], row["kind"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    rows = deduped

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
