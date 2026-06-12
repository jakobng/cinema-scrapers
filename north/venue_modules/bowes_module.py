# The Bowes Museum, Barnard Castle
# The /exhibitions/ page is a title-only menu (Current/Future Exhibitions);
# dates and images are filled by the detail-page enrichment pass.
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import norm

BASE_URL = "https://thebowesmuseum.org.uk"
EXHIBITIONS_URL = "https://thebowesmuseum.org.uk/exhibitions/"
VENUE_NAME = "The Bowes Museum"
VENUE_CITY = "Barnard Castle"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

_SKIP_TITLES = ("exhibitions", "what's on", "whats on", "current exhibitions", "future exhibitions", "past exhibitions")


def scrape_bowes():
    r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").split("#")[0].strip()
        if "/exhibitions/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if slug in ("exhibitions", ""):
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        title = norm(a.get_text())
        if not title or len(title) < 3 or title.lower() in _SKIP_TITLES:
            continue
        seen.add(full_url)
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": None,
            "end_date": None,
            "detail_page_url": full_url,
            "description": None,
            "image_url": None,
        })
    return out
