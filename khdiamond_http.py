"""HTTP and HTML helpers for the current khdiamond.net DooPlay site."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

SITE_URL = "https://khdiamond.net/"

NONCE_PATTERNS = (
    re.compile(r'\bdtAjax\s*=\s*\{.*?["\']nonce["\']\s*:\s*["\']([^"\']+)', re.S),
    re.compile(r'["\']nonce["\']\s*:\s*["\']([^"\']+)["\']'),
)
POST_ID_RE = re.compile(r"\bpostid-(\d+)\b")
MEDIA_ID_PATTERNS = (
    re.compile(r"/hls/([A-Za-z0-9_-]+)/", re.I),
    re.compile(r"player(?:\.kh-diamond\.net)?/(?:\d+/){0,3}([A-Za-z0-9_-]{6,})(?:[/?#]|$)", re.I),
    re.compile(r"[?&](?:id|video|movie_id)=([A-Za-z0-9_-]{6,})", re.I),
)


def extract_nonce(page_html: str) -> str:
    for pattern in NONCE_PATTERNS:
        match = pattern.search(page_html or "")
        if match:
            return match.group(1)
    return ""


def extract_post_id(page_html: str) -> str:
    match = POST_ID_RE.search(page_html or "")
    return match.group(1) if match else ""


def response_embed_url(response) -> str:
    """Return an embed URL from DooPlay's JSON or HTML-shaped response."""
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        data = response.text

    if isinstance(data, dict):
        value = data.get("embed_url") or data.get("url") or data.get("embed") or ""
    elif isinstance(data, str):
        value = data
    else:
        value = ""

    value = html.unescape(str(value)).replace("\\/", "/").strip()
    if value.startswith(("http://", "https://")):
        return value
    soup = BeautifulSoup(value, "html.parser")
    tag = soup.select_one("iframe[src], source[src], video[src]")
    return tag.get("src", "") if tag else value


def extract_media_id(embed_url: str) -> str:
    value = html.unescape(embed_url or "").replace("\\/", "/")
    for pattern in MEDIA_ID_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return ""


def is_login_page(response) -> bool:
    final_path = urlparse(response.url).path.rstrip("/")
    soup = BeautifulSoup(response.text, "html.parser")
    has_login_form = bool(soup.select_one(
        "form#loginform, form.login, input[name='log'][type='text'], input[name='pwd']"
    ))
    account_body = soup.select_one("body.logged-in, body.woocommerce-account")
    return response.status_code in (401, 403) or (
        has_login_form and not account_body and final_path.endswith("my-account")
    )


def library_rows(page_html: str, base_url: str = SITE_URL) -> list[dict]:
    """Extract purchased movie/series cards without relying on one card layout."""
    soup = BeautifulSoup(page_html, "html.parser")
    path_re = re.compile(r"/(movies|tvshows|series|tvshow)/([^/?#]+)/?")
    rows = []
    seen = set()
    for link in soup.select("article a[href], .page_user a[href], .items a[href]"):
        absolute = urljoin(base_url, link.get("href", ""))
        match = path_re.search(absolute)
        if not match:
            continue
        kind, slug = match.groups()
        kind = "tvshows" if kind in ("series", "tvshow") else kind
        key = (kind, slug)
        if key in seen:
            continue
        card = link.find_parent("article") or link.find_parent("div")
        title_node = card.select_one("h2, h3, .data h3, .title") if card else None
        title = (title_node or link).get_text(" ", strip=True)
        if not title:
            image = link.select_one("img[alt]")
            title = image.get("alt", "").strip() if image else ""
        year_node = card.select_one(".data span, .year, .date") if card else None
        year_match = re.search(r"\b(?:19|20)\d{2}\b", year_node.get_text(" ", strip=True) if year_node else "")
        article = link.find_parent("article")
        rows.append({
            "slug": slug, "title": title or slug, "kind": kind,
            "year": year_match.group(0) if year_match else "",
            "page_url": absolute, "article_id": article.get("id", "") if article else "",
        })
        seen.add(key)
    return rows
