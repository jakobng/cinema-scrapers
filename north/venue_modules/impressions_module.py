# Impressions Gallery, Bradford (photography)
from datetime import date, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm, card_text_for

BASE_URL = "https://www.impressions-gallery.com"
EXHIBITIONS_URL = "https://www.impressions-gallery.com/exhibitions/"
VENUE_NAME = "Impressions Gallery"
VENUE_CITY = "Bradford"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def scrape_impressions():
    r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").split("#")[0].strip()
        if "/event/" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        card = a
        for _ in range(4):
            if card.parent and len(norm(card.get_text())) < 25:
                card = card.parent
        card_text = card_text_for(a)
        low = card_text.lower()
        # Keep gallery exhibitions only; skip virtual-only and touring shows
        if low.startswith("virtual exhibition") or low.startswith("on tour"):
            continue
        if not low.startswith("exhibition"):
            continue
        title = card_text
        if title.lower().startswith("exhibition"):
            title = title[len("exhibition"):].strip()
        # Strip trailing date/price text from the title
        for sep in (" 0", " 1", " 2", " 3", " – FREE", " - FREE"):
            idx = title.find(sep)
            if idx > 3:
                title = title[:idx]
                break
        title = norm(title)
        if not title or len(title) < 3:
            continue
        seen.add(full_url)
        start, end = parse_date_range(card_text)
        # The exhibitions page includes the archive; skip long-finished shows
        if end and end < (date.today() - timedelta(days=21)).isoformat():
            continue
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
