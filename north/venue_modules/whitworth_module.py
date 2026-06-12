#!/usr/bin/env python3
# Whitworth Art Gallery, Manchester - exhibitions scraper
#
# The /whats-on/exhibitions/ listing renders its current exhibitions as a
# <ul class="gridList"> of <li> cards. Each card carries the title, a blurb,
# a /whats-on/exhibitions/<slug>/ link, and the real listing image inside a
# <noscript> wrapper (the visible <img> is a lazy-load base64 placeholder, and
# the detail pages expose no og:image - which is why enrichment found nothing).
# Dates aren't on the listing but appear in the detail-page text
# ("14 March - 15 November 2026"), so we fetch each detail page for the date.

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import norm, parse_uk_date_text

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

DETAIL_RE = re.compile(r"/whats-on/exhibitions/[a-z0-9][a-z0-9-]+/?$", re.IGNORECASE)
# Category/listing pages that aren't individual exhibitions.
SKIP_SLUGS = ("touringexhibitions", "pastexhibitions")
# A headline date range or open-ended date as written on the detail page. The
# first date's year is optional ("14 March - 15 November 2026") or present
# ("30 September 2025 - 4 April 2027").
DATE_TEXT_RE = re.compile(
    r"\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?\s*[–—-]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|(?:until|from)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}",
    re.IGNORECASE,
)


def _noscript_image(li):
    """The real listing image is an <img> inside a <noscript> in the card."""
    ns = li.find("noscript")
    if ns:
        inner = BeautifulSoup(ns.decode_contents(), "html.parser").find("img")
        if inner and inner.get("src"):
            return urljoin(BASE_URL, inner["src"])
    # Fallback: a lazy <img> whose data-src holds the real URL.
    for img in li.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if src and not src.startswith("data:"):
            return urljoin(BASE_URL, src)
    return None


def _detail_dates(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception:
        return None, None
    soup = BeautifulSoup(r.text, "html.parser")
    text = norm((soup.find("main") or soup.body or soup).get_text(" "))
    m = DATE_TEXT_RE.search(text)
    return parse_uk_date_text(m.group(0)) if m else (None, None)


def scrape_whitworth():
    """Return list of exhibition dicts for The Whitworth."""
    try:
        r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {EXHIBITIONS_URL}: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    seen = set()
    for grid in soup.find_all("ul", class_="gridList"):
        for li in grid.find_all("li", recursive=False):
            a = li.find("a", href=DETAIL_RE)
            if not a:
                continue
            detail_url = urljoin(BASE_URL, a["href"])
            if detail_url in seen or any(sl in detail_url.lower() for sl in SKIP_SLUGS):
                continue
            heading = li.find(["h1", "h2", "h3", "h4"])
            title = norm(heading.get_text()) if heading else norm(a.get_text())
            if not title or len(title) < 3:
                continue

            start_str, end_str = _detail_dates(detail_url)
            seen.add(detail_url)
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": title[:500],
                "start_date": start_str,
                "end_date": end_str,
                "detail_page_url": detail_url,
                "description": None,
                "image_url": _noscript_image(li),
            })
    return out


if __name__ == "__main__":
    for row in scrape_whitworth():
        print(f"{'IMG' if row['image_url'] else '---'} "
              f"{str(row['start_date']):>10}..{str(row['end_date']):<10} | {row['exhibition_title'][:50]}")
