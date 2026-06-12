# Open Eye Gallery, Liverpool (whatson page is JS-heavy; we try scrape then fallback)
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://openeye.org.uk"
WHATSON_URL = "https://openeye.org.uk/whatson"
VENUE_NAME = "Open Eye Gallery"
VENUE_CITY = "Liverpool"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

FALLBACK = [
    {"title": "The Flowers Still Grow", "slug": "the-flowers-still-grow"},
    {"title": "For Your Pleasure: 15 Years Of DuoVision", "slug": "for-your-pleasure"},
    {"title": "LOOK Climate Lab 2026", "slug": "look-climate-lab-2026"},
]

def scrape_open_eye():
    out = []
    try:
        r = requests.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch " + WHATSON_URL + ": " + str(e)) from e
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href.startswith("/") or "whatson" not in href and "exhibition" not in href and "event" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url == WHATSON_URL or full_url == WHATSON_URL + "/":
            continue
        title = norm(a.get_text())
        if not title or len(title) < 3:
            continue
        if title.lower() in ("see more", "what's on", "load more", "plan your visit"):
            continue
        date_text = ""
        parent = a.parent
        for _ in range(5):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            parent = parent.parent
        start_str, end_str = parse_date_range(date_text)
        out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": title[:500], "start_date": start_str, "end_date": end_str, "detail_page_url": full_url, "description": None, "image_url": None})
    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(item)
    if not unique:
        for fb in FALLBACK:
            unique.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": fb["title"],
                "start_date": None,
                "end_date": None,
                "detail_page_url": urljoin(BASE_URL, "/whatson/" + fb["slug"] + "/"),
                "description": None,
                "image_url": None,
            })
    return unique
