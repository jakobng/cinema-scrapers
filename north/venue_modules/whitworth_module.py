#!/usr/bin/env python3
# Whitworth Art Gallery, Manchester - exhibitions scraper

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm, get_page_meta

BASE_URL = "https://www.whitworth.manchester.ac.uk"
EXHIBITIONS_URL = f"{BASE_URL}/whats-on/exhibitions/"
VENUE_NAME = "The Whitworth"
VENUE_CITY = "Manchester"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def scrape_whitworth():
    """Return list of exhibition dicts for The Whitworth."""
    out = []
    try:
        r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {EXHIBITIONS_URL}: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or "whats-on/exhibitions/" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url.rstrip("/") == EXHIBITIONS_URL.rstrip("/"):
            continue
        if "/pastexhibitions/" in href or "/touringexhibitions/" in href:
            continue
        title = norm(a.get_text())
        if not title or len(title) < 2:
            continue
        if title.lower() in ("read more", "more info", "exhibitions"):
            continue

        date_text = ""
        start_str, end_str = None, None
        parent = a.parent
        for _ in range(5):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            start_str, end_str = parse_date_range(date_text)
            if start_str or end_str:
                break
            parent = parent.parent

        if not start_str and not end_str:
            start_str, end_str = parse_date_range(date_text or a.get_text())

        meta = get_page_meta(full_url, headers=HEADERS, timeout=TIMEOUT)
        exhibition_title = (meta.get("title") or title)[:500]
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": exhibition_title,
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": full_url,
            "description": meta.get("description"),
            "image_url": meta.get("image_url"),
        })

    seen = set()
    unique = []
    for item in out:
        key = item["detail_page_url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique
