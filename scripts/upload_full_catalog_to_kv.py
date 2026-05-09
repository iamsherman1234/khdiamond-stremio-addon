#!/usr/bin/env python3
"""Upload full_catalog.json to Cloudflare KV for the catalog addon."""
import os, json, requests
from pathlib import Path

CATALOG_PATH = Path("/root/khdiamond/full_catalog.json")
CF_ACCOUNT_ID   = os.environ.get("CF_ACCOUNT_ID", "7eb3af74ef7bf1bee7d082b1466e4ef7")
CF_KV_NAMESPACE = "751a13189e3144bf99d978b086ce8551"
CF_API_TOKEN    = os.environ.get("CLOUDFLARE_API_TOKEN", "")

def upload():
    if not CF_API_TOKEN:
        print("⚠ CLOUDFLARE_API_TOKEN not set — skipping")
        return
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    catalog = json.loads(raw)
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE}/values/full_catalog.json"
    r = requests.put(url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
        data=raw, timeout=60)
    if r.ok:
        print(f"✓ Uploaded full_catalog.json to KV ({len(catalog)} entries)")
    else:
        print(f"✗ KV upload failed: {r.status_code} {r.text[:200]}")

if __name__ == "__main__":
    upload()
