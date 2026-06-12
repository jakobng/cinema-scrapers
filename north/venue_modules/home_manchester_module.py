# HOME, Manchester — art exhibitions listing
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, parse_short_date_range, norm, card_text_for

BASE_URL = "https://homemcr.org"
ART_URL = "https://homemcr.org/whats-on/art"
VENUE_NAME = "HOME"
VENUE_CITY = "Manchester"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 30

# One-off events on the art listing we don't want as "exhibitions"
_SKIP_TITLE_RE = re.compile(
    r"workshop|launch event|tour|family|drop-in|in conversation|artist talk|opening night",
    re.IGNORECASE,
)
# Button/CTA anchor text that is not a title
_CTA_TITLE_RE = re.compile(
    r"^(?:book now|book tickets|no booking required|find out more|more info|read more|see everything|not for sale)$",
    re.IGNORECASE,
)


def scrape_home():
    r = requests.get(ART_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").split("#")[0].strip()
        if "/whats-on/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if slug in ("whats-on", "art") or not slug:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        # Walk up to the card element to get title + date text
        card = a
        for _ in range(4):
            if card.parent and len(norm(card.get_text())) < 25:
                card = card.parent
        card_text = card_text_for(a)
        title = norm(a.get_text())
        if not title:
            heading = card.find(["h2", "h3", "h4"])
            title = norm(heading.get_text()) if heading else ""
        if not title or len(title) < 3:
            continue
        if _SKIP_TITLE_RE.search(title) or _CTA_TITLE_RE.match(title):
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
