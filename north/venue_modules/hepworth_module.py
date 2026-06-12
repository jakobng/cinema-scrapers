#!/usr/bin/env python3
# The Hepworth Wakefield - exhibitions scraper

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm

BASE_URL = "https://hepworthwakefield.org"
EXHIBITIONS_CATEGORY_URL = f"{BASE_URL}/whats-on/categories/exhibitions/"
VENUE_NAME = "The Hepworth Wakefield"
VENUE_CITY = "Wakefield"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def scrape_hepworth():
    """Return list of exhibition dicts for The Hepworth Wakefield."""
    out = []
    try:
        r = requests.get(EXHIBITIONS_CATEGORY_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {EXHIBITIONS_CATEGORY_URL}: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")

    # The Hepworth site uses cards (often <article> or <div class="card">)
    # We look for containers that include a link to /whats-on/ and an image
    for card in soup.find_all(["article", "div"], class_=re.compile(r"card|item|post|event", re.I)):
        a = card.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href or "/whats-on/" not in href or "/categories/" in href or "/page/" in href:
            continue
        
        full_url = urljoin(BASE_URL, href)
        
        # Title is often in an h2 or h3 inside the card
        title_el = card.find(["h2", "h3"])
        title = norm(title_el.get_text()) if title_el else norm(a.get_text())
        
        if not title or len(title) < 3 or title.lower() in ("more info", "read more", "exhibitions"):
            continue

        # Image
        img_url = None
        img = card.find("img")
        if img and img.get("src"):
            img_url = urljoin(BASE_URL, img.get("src"))

        # Dates
        date_text = card.get_text(separator=" ")
        start_str, end_str = parse_date_range(date_text)

        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": full_url,
            "description": None,
            "image_url": img_url,
        })

    # Fallback to old link-based search if no cards found
    if not out:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or "/whats-on/" not in href or "/categories/" in href or "/page/" in href:
                continue
            full_url = urljoin(BASE_URL, href)
            title = norm(a.get_text())
            if not title or len(title) < 3 or title.lower() in ("more info", "read more", "exhibitions"):
                continue
            date_text = a.parent.get_text(separator=" ") if a.parent else ""
            start_str, end_str = parse_date_range(date_text)
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": title[:500],
                "start_date": start_str,
                "end_date": end_str,
                "detail_page_url": full_url,
                "description": None,
                "image_url": None,
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
