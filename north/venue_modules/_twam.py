#!/usr/bin/env python3
# Shared scraper for Tyne & Wear Archives & Museums venues, which all run on the
# same northeastmuseums.org.uk CMS (a Yii "what's on" search). Each venue's
# /<venue>/whats-on page redirects to /whats-on/search/<kw>/<from>/<to>/<cats>/<aud>/<venueId>.
# Filtering to category 27 (Exhibitions) and the venue id returns exhibitions and
# displays only - no events, classes or tours. Cards are uniform:
#
#   div.event-grid-item > a[href=/<venue>/whats-on/<slug>]
#       div.event-image > img.img-responsive   (full CloudFront URL)
#       div.event-detail > h3 (title), p.event-grid-date ("Permanent" or a range)
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import norm, parse_uk_date_text

BASE_URL = "https://www.northeastmuseums.org.uk"
EXHIBITIONS_CATEGORY = "27"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def scrape_twam_venue(venue_id, venue_name, venue_city):
    """Return exhibition dicts for one Tyne & Wear museum (by numeric venue id)."""
    url = f"{BASE_URL}/whats-on/search/-/-/-/{EXHIBITIONS_CATEGORY}/-/{venue_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {venue_name} ({url}): {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    seen = set()
    for card in soup.select("div.event-grid-item"):
        a = card.find("a", href=re.compile(r"/whats-on/[a-z0-9-]{3,}/?$", re.I))
        if not a:
            continue
        detail_url = urljoin(BASE_URL, a["href"].split("?")[0])
        if detail_url in seen:
            continue

        heading = card.find(["h2", "h3", "h4"])
        title = norm(heading.get_text()) if heading else ""
        if not title or len(title) < 3:
            continue

        date_el = card.select_one(".event-grid-date")
        # "Permanent" / "Continuing display" -> ongoing (None, None); ranges parsed.
        start_str, end_str = parse_uk_date_text(date_el.get_text(" ") if date_el else "")

        img = card.find("img")
        image_url = urljoin(BASE_URL, img["src"]) if img and img.get("src") else None

        summary = card.select_one(".event-grid-summary")
        description = norm(summary.get_text(" "))[:1000] if summary else None

        seen.add(detail_url)
        out.append({
            "venue_name": venue_name,
            "venue_city": venue_city,
            "exhibition_title": title[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": detail_url,
            "description": description,
            "image_url": image_url,
        })
    return out
