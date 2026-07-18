#!/usr/bin/env python3
"""Report full-catalog identity coverage without printing secrets."""
import json
import os
import re
from collections import Counter
from pathlib import Path


CATALOG_PATH = Path(os.environ.get("FULL_CATALOG_PATH", "/root/khdiamond/full_catalog.json"))
IMDB_RE = re.compile(r"^tt\d{7,10}$")


def valid_poster(value: str) -> bool:
    value = str(value or "").strip()
    return (
        value.startswith(("http://", "https://"))
        and "/themes/dooplay/assets/img/" not in value.lower().split("?", 1)[0]
    )


def main() -> int:
    try:
        catalog = json.loads(CATALOG_PATH.read_text())
    except Exception as exc:
        print(f"ERROR: cannot read {CATALOG_PATH}: {exc}")
        return 1
    if not isinstance(catalog, list):
        print("ERROR: catalog root must be a JSON list")
        return 1

    ids = [str(item.get("imdb_id") or "") for item in catalog]
    valid_ids = [value for value in ids if IMDB_RE.fullmatch(value)]
    duplicate_ids = {value: count for value, count in Counter(valid_ids).items() if count > 1}
    custom = [item for item in catalog if not IMDB_RE.fullmatch(str(item.get("imdb_id") or ""))]

    print(f"Catalog: {CATALOG_PATH}")
    print(f"Total: {len(catalog)}")
    print(f"Movies: {sum(item.get('type') == 'movie' for item in catalog)}")
    print(f"Series: {sum(item.get('type') == 'series' for item in catalog)}")
    print(f"Valid IMDb IDs: {len(valid_ids)}")
    print(f"KhDiamond-only IDs: {len(custom)}")
    print(f"Posters: {sum(valid_poster(item.get('poster')) or valid_poster(item.get('tmdb_poster')) for item in catalog)}")
    placeholders = [item for item in catalog
                    if item.get("poster") and not valid_poster(item.get("poster"))]
    print(f"Placeholder posters: {len(placeholders)}")
    print(f"Original titles: {sum(bool(item.get('original_title')) for item in catalog)}")
    print(f"Duplicate IMDb IDs: {len(duplicate_ids)}")
    for imdb_id, count in sorted(duplicate_ids.items()):
        titles = [item.get("title_english") or item.get("title_khmer")
                  for item in catalog if item.get("imdb_id") == imdb_id]
        print(f"  {imdb_id} x{count}: {' | '.join(str(title) for title in titles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
