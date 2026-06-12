# National Science and Media Museum, Bradford
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, norm

BASE_URL = "https://www.scienceandmediamuseum.org.uk"
WHATSON_URL = "https://www.scienceandmediamuseum.org.uk/whats-on"
VENUE_NAME = "National Science and Media Museum"
VENUE_CITY = "Bradford"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

# Card categories we treat as exhibitions (skip talks, festivals, online-only,
# and the museum's permanent galleries — the directory lists shows, not venues)
_KEEP_CATEGORIES = ("temporary display", "temporary exhibition", "exhibition")
_SKIP_CATEGORIES = ("online exhibition", "permanent gallery", "special event", "talk", "festival", "accessible event")


def scrape_nsmm():
    r = requests.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").split("#")[0].strip()
        if not href.startswith("/whats-on/") or href.rstrip("/") == "/whats-on":
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        card_text = norm(a.get_text(" "))
        low = card_text.lower()
        if "category:" not in low:
            continue
        category = low.split("category:", 1)[1].strip()
        if any(category.startswith(s) for s in _SKIP_CATEGORIES):
            continue
        if not any(category.startswith(k) for k in _KEEP_CATEGORIES):
            continue
        title = card_text.split("Category:")[0].strip()
        if not title or len(title) < 3:
            continue
        seen.add(full_url)
        start, end = parse_date_range(card_text)
        if start and start == end:
            end = None  # single date on a card means "opens", not a one-day show
        img = a.find("img")
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
