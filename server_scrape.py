#!/usr/bin/env python3
"""
server_scrape.py — Scrape khdiamond.net purchases → 'library_raw' sheet
Server version of phase1_scrape.py (no Colab dependency).

Reads cookies from /root/khdiamond/cookies.txt
Auth via GDRIVE_SERVICE_ACCOUNT env var (service account JSON)
"""
import re
import sys
from pathlib import Path
from http.cookiejar import MozillaCookieJar

import requests
import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, "/root/khdiamond")
from drive_manager import get_gspread_client

SPREADSHEET_ID = "1gAjrURaRX3ce1gf-KyUw2UOlwYX3aEYc_7YnQD6T-5g"
LIBRARY_URL    = "https://khdiamond.net/my-account/"
COOKIES_PATH   = Path("/root/khdiamond/cookies.txt")
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
        sys.exit("❌ Got login page — cookies expired. Re-export and update cookies.txt.")

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

    df = pd.DataFrame(rows).drop_duplicates(subset=["slug", "kind"])

    if df.empty:
        sys.exit("❌ Zero items parsed — check cookies or site structure.")

    print(f"\n✓ Extracted {len(df)} items")
    print(df["kind"].value_counts().to_string())

    missing_aid = (df["article_id"] == "").sum()
    if missing_aid > 0:
        print(f"⚠ {missing_aid} rows have empty article_id — resolver will skip them.")

    print("\n→ Writing to Sheets...")
    gc = get_gspread_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet("library_raw")
        ws.clear()
    except Exception:
        ws = ss.add_worksheet(title="library_raw", rows=200, cols=6)
    ws.update([df.columns.tolist()] + df.values.tolist())
    print(f"✓ Wrote {len(df)} rows to 'library_raw'")


if __name__ == "__main__":
    main()
