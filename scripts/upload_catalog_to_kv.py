#!/usr/bin/env python3
import os
import json
import sys
import requests
from pathlib import Path

CATALOG_PATH = Path(os.environ.get("CATALOG_PATH", "/root/khdiamond/catalog.json"))
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_KV_NAMESPACE = os.environ.get("CF_KV_NAMESPACE", "")
CF_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")

def upload_catalog():
    missing = [
        name for name, value in {
            "CLOUDFLARE_API_TOKEN": CF_API_TOKEN,
            "CF_ACCOUNT_ID": CF_ACCOUNT_ID,
            "CF_KV_NAMESPACE": CF_KV_NAMESPACE,
        }.items() if not value
    ]
    if missing:
        print(f"Missing required environment: {', '.join(missing)}", file=sys.stderr)
        return False
    if not CATALOG_PATH.exists():
        print(f"Catalog file not found: {CATALOG_PATH}", file=sys.stderr)
        return False
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    catalog = json.loads(raw)
    if not isinstance(catalog, list):
        print("Catalog JSON must be an array", file=sys.stderr)
        return False
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE}/values/catalog.json"
    r = requests.put(url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
        data=raw, timeout=30)
    if r.ok:
        print(f"✓ Uploaded catalog.json to Cloudflare KV ({len(catalog)} entries, {len(raw)//1024}KB)")
        return True
    else:
        print(f"✗ KV upload failed: {r.status_code} {r.text[:200]}")
        return False

if __name__ == "__main__":
    raise SystemExit(0 if upload_catalog() else 1)
