# Nottingham Contemporary — within easy day-trip range of Sheffield
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, parse_short_date_range, norm, card_text_for

BASE_URL = "https://www.nottinghamcontemporary.org"
WHATSON_URL = "https://www.nottinghamcontemporary.org/whats-on/"
VENUE_NAME = "Nottingham Contemporary"
VENUE_CITY = "Nottingham"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def scrape_nottingham_contemporary():
    r = requests.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").split("#")[0].strip()
        if "/whats-on/" not in href or href.rstrip("/").endswith("whats-on"):
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        card = a
        for _ in range(4):
            if card.parent and len(norm(card.get_text())) < 25:
                card = card.parent
        card_text = card_text_for(a)
        # Keep only items labelled as exhibitions (Current/Upcoming Exhibition)
        if "exhibition" not in card_text.lower():
            continue
        title = norm(a.get_text())
        if not title:
            heading = card.find(["h2", "h3", "h4"])
            title = norm(heading.get_text()) if heading else ""
        # Strip trailing card labels from anchor text
        for marker in (" Current Exhibition", " Upcoming Exhibition", " Exhibition"):
            idx = title.find(marker)
            if idx > 3:
                title = title[:idx]
                break
        title = norm(title)
        if not title or len(title) < 3:
            continue
        seen.add(full_url)
        start, end = parse_date_range(card_text)
        if not (start or end):
            start, end = parse_short_date_range(card_text)
        img = card.find("img")
        img_url = None
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src and not src.startswith("data:"):
                img_url = urljoin(BASE_URL, src)
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": start,
            "end_date": end,
            "detail_page_url": full_url,
            "description": None,
            "image_url": img_url,
        })
    return out
