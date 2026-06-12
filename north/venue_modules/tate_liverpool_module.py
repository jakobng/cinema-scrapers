#!/usr/bin/env python3
# Tate Liverpool - exhibitions scraper

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import norm

BASE_URL = "https://www.tate.org.uk"
# Liverpool-filtered what's on (exhibitions and events); we filter to exhibitions only, no daily/recurring
WHATS_ON_URL = f"{BASE_URL}/whats-on?date_range=from_now&gallery_group=tate-liverpool"

VENUE_NAME = "Tate Liverpool"
VENUE_CITY = "Liverpool"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def _parse_tate_date(text):
    """e.g. 'Until 14 Jun 2026' or '14 Jun 2026' -> (None, '2026-06-14') or single date."""
    if not text:
        return None, None
    text = text.strip()
    # Until DD Mon YYYY
    m = re.search(r"(?:until|until\s+)(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})", text, re.I)
    if m:
        d, mon, y = m.groups()
        months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
        try:
            mo = months.index(mon.lower()) + 1
            end = f"{y}-{mo:02d}-{int(d):02d}"
            return None, end
        except (ValueError, IndexError):
            pass
    # DD Mon YYYY
    m = re.search(r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})", text, re.I)
    if m:
        d, mon, y = m.groups()
        months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
        try:
            mo = months.index(mon.lower()) + 1
            single = f"{y}-{mo:02d}-{int(d):02d}"
            return single, single
        except (ValueError, IndexError):
            pass
    return None, None


def _skip_daily_or_workshop(link_text):
    """Exclude recurring/daily events and workshops; keep exhibitions and one-off displays. Use link text only so we don't match other cards."""
    if not link_text:
        return True
    lower = link_text.lower()
    if "every day" in lower or "available every day" in lower or "daily," in lower:
        return True
    if link_text.strip().lower().startswith("workshop "):
        return True
    return False


def scrape_tate_liverpool():
    """Return list of exhibition dicts for Tate Liverpool (exhibitions and displays only, no daily/workshop events)."""
    out = []
    try:
        r = requests.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch " + WHATS_ON_URL + ": " + str(e)) from e
    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if "liverpool" not in href.lower():
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url.rstrip("/").endswith("/visit/tate-liverpool") or full_url.rstrip("/").endswith("/whats-on"):
            continue
        path = href.split("?")[0].rstrip("/")
        if "/whats-on/" in href and "tate-liverpool" in href.lower():
            if path.endswith("tate-liverpool") or path.endswith("tate-liverpool--riba-north"):
                continue
        elif "?" in href and "gallery_group=" in href and "/whats-on" not in href.split("?")[0]:
            continue
        # Skip filter/listing links (whats-on with no event slug)
        if path.rstrip("/").endswith("/whats-on"):
            continue

        raw_title = a.get_text(separator=" ", strip=True)
        if _skip_daily_or_workshop(raw_title):
            continue
        # Strip leading "Exhibition " and trim description (before " Tate Liverpool" / " Until " / description verbs)
        title = norm(raw_title)
        if title.lower().startswith("exhibition "):
            title = title[11:].strip()
        for sep in (" Tate Liverpool", " Until ", " Free "):
            if sep.lower() in title.lower():
                title = title.split(sep)[0].strip()
        for sep in (" Follow ", " This ", " Explore ", " Help ", " Break ", " Discover "):
            if sep in title and title.index(sep) > 15:
                title = title.split(sep)[0].strip()
                break
        if not title or len(title) < 3:
            continue
        if title.lower() in ("read more", "book now", "what's on", "all displays and events", "tate liverpool", "get directions", "getting here"):
            continue

        start_str, end_str = _parse_tate_date(raw_title)
        parent = a.parent
        for _ in range(5):
            if not parent:
                break
            t = parent.get_text(separator=" ")
            if not start_str and not end_str:
                start_str, end_str = _parse_tate_date(t)
            if start_str or end_str:
                break
            parent = parent.parent

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
