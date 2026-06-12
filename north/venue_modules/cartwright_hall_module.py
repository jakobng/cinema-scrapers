#!/usr/bin/env python3
# Cartwright Hall Art Gallery, Bradford - exhibitions
# Source: bradfordmuseums.org/whats-on/exhibitions/ (has venue names and dates)

from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm

BASE_URL = "https://www.bradfordmuseums.org"
EXHIBITIONS_URL = f"{BASE_URL}/whats-on/exhibitions/"
VENUE_NAME = "Cartwright Hall Art Gallery"
VENUE_CITY = "Bradford"

# Venue names as they appear on the exhibitions page (we only return Cartwright Hall)
BRADFORD_VENUES = (
    "Cartwright Hall Art Gallery",
    "Bradford Industrial Museum",
    "Bolling Hall Museum",
    "Cliffe Castle Museum",
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def _minimal_blocks_with_date_and_link(soup):
    """Find minimal elements that contain both a parseable date range and an /event/ link."""
    candidates = []
    for tag in soup.find_all(True):
        text = tag.get_text(separator=" ", strip=True)
        if parse_date_range(text)[0] is None:
            continue
        if not any("/event/" in (a.get("href") or "") for a in tag.find_all("a", href=True)):
            continue
        candidates.append(tag)
    minimal = [
        c for c in candidates
        if not any(d != c and d in c.descendants and d in candidates for d in candidates)
    ]
    return minimal


def _title_from_block(block, link):
    """Exhibition title: link text, or first heading in block if link says 'Learn More'."""
    link_text = norm(link.get_text())
    if link_text and link_text.lower() not in ("learn more", "view all"):
        return link_text[:500]
    for tag in block.find_all(["h1", "h2", "h3", "h4", "h5"]):
        t = norm(tag.get_text())
        if t and len(t) > 2:
            return t[:500]
    return link_text or None


def _scrape_bradford_exhibitions_page():
    """Fetch exhibitions page and yield (venue_name, title, start_date, end_date, detail_page_url) for each exhibition."""
    try:
        r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch " + EXHIBITIONS_URL + ": " + str(e)) from e
    soup = BeautifulSoup(r.text, "html.parser")

    for block in _minimal_blocks_with_date_and_link(soup):
        text = block.get_text(separator=" ", strip=True)
        start_str, end_str = parse_date_range(text)
        if not start_str:
            continue
        venue = next((v for v in BRADFORD_VENUES if v in text), None)
        if not venue:
            continue
        for a in block.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if "/event/" not in href:
                continue
            full_url = urljoin(BASE_URL, href)
            title = _title_from_block(block, a)
            if not title or len(title) < 2:
                continue
            yield venue, title, start_str, end_str, full_url


def _scrape_bradford_venue(venue_name):
    """Return exhibition dicts for one Bradford venue (same page, filter by venue)."""
    out = []
    seen = set()
    for venue, title, start_str, end_str, full_url in _scrape_bradford_exhibitions_page():
        if venue != venue_name:
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        out.append({
            "venue_name": venue_name,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": full_url,
            "description": None,
            "image_url": None,
        })
    return out


def scrape_cartwright_hall():
    """Return list of exhibition dicts for Cartwright Hall (Bradford)."""
    return _scrape_bradford_venue(VENUE_NAME)


def scrape_bradford_industrial_museum():
    """Return list of exhibition dicts for Bradford Industrial Museum."""
    return _scrape_bradford_venue("Bradford Industrial Museum")


def scrape_bolling_hall():
    """Return list of exhibition dicts for Bolling Hall Museum."""
    return _scrape_bradford_venue("Bolling Hall Museum")


def scrape_cliffe_castle():
    """Return list of exhibition dicts for Cliffe Castle Museum."""
    return _scrape_bradford_venue("Cliffe Castle Museum")
