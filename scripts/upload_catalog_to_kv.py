#!/usr/bin/env python3
import os, json, requests
from pathlib import Path

CATALOG_PATH = Path("/root/khdiamond/catalog.json")
CF_ACCOUNT_ID  = os.environ.get("CF_ACCOUNT_ID", "7eb3af74ef7bf1bee7d082b1466e4ef7")
CF_KV_NAMESPACE = os.environ.get("CF_KV_NAMESPACE", "0aeaa16e22bc44ea9df2bc10583dae72")
CF_API_TOKEN   = os.environ.get("CLOUDFLARE_API_TOKEN", "")

def upload_catalog():
    if not CF_API_TOKEN:
        print("⚠ CLOUDFLARE_API_TOKEN not set — skipping KV upload")
        return False
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    catalog = json.loads(raw)
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
    upload_catalog()
