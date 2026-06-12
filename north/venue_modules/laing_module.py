#!/usr/bin/env python3
# Laing Art Gallery, Newcastle - exhibitions and displays

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm, get_page_meta

BASE_URL = "https://www.twmuseums.org.uk"
LAING_WHATS_ON = "https://www.northeastmuseums.org.uk/laing/whats-on"
VENUE_NAME = "Laing Art Gallery"
VENUE_CITY = "Newcastle"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def _parse_until_date(text):
    """e.g. 'Until 5 Dec' or 'Until 31 Dec' -> end_date."""
    m = re.search(r"until\s+(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:\s+(\d{4}))?", text, re.I)
    if m:
        d, mon, y = m.groups()
        y = y or "2026"
        months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
        try:
            mo = months.index(mon.lower()) + 1
            return f"{y}-{mo:02d}-{int(d):02d}"
        except (ValueError, IndexError):
            pass
    return None


def _slug_to_title(slug):
    """Convert URL slug to exhibition title (e.g. 'kramer-portrait-award' -> 'Kramer Portrait Award')."""
    if not slug:
        return ""
    return " ".join(w.capitalize() for w in slug.split("-"))


def scrape_laing():
    """Return list of exhibition/display dicts for Laing Art Gallery."""
    out = []
    try:
        r = requests.get(LAING_WHATS_ON, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {LAING_WHATS_ON}: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/laing/whats-on/" not in href:
            continue
        full_url = urljoin("https://www.northeastmuseums.org.uk", href)
        if full_url.rstrip("/") == LAING_WHATS_ON.rstrip("/"):
            continue
        path = href.split("?")[0].rstrip("/")
        slug = path.split("/laing/whats-on/")[-1].strip("/") if "/laing/whats-on/" in path else ""
        if not slug:
            continue
        title = _slug_to_title(slug)
        if not title or len(title) < 3:
            continue
        date_text = ""
        parent = a.parent
        for _ in range(5):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            parent = parent.parent
        start_str, end_str = parse_date_range(date_text)
        if not end_str and date_text:
            end_str = _parse_until_date(date_text)
        meta = get_page_meta(full_url, headers=HEADERS, timeout=TIMEOUT)
        meta_title = meta.get("title") or ""
        if meta_title and " | " in meta_title:
            meta_title = meta_title.split(" | ")[0].strip()
        if meta_title and len(meta_title) <= 120 and "Laing Art Gallery" not in meta_title:
            exhibition_title = meta_title[:500]
        else:
            exhibition_title = title[:500]
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
