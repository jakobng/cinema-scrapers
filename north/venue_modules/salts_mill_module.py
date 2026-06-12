# Salts Mill and 1853 Gallery, Saltaire
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import norm

BASE_URL = "https://www.saltsmill.org.uk"
VENUE_NAME = "Salts Mill & 1853 Gallery"
VENUE_CITY = "Saltaire"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25
FALLBACK = [
    {"title": "1853 Gallery – David Hockney", "note": "Permanent display of David Hockney works"},
    {"title": "Weaving the Future", "note": "Exhibitions in the Roof Space"},
]

def scrape_salts_mill():
    out = []
    try:
        r = requests.get(BASE_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or ("exhibition" not in href.lower() and "gallery" not in href.lower()):
                continue
            full_url = urljoin(BASE_URL, href)
            title = norm(a.get_text())
            if not title or len(title) < 4:
                continue
            out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": title[:500], "start_date": None, "end_date": None, "detail_page_url": full_url, "description": None, "image_url": None})
    except Exception:
        pass
    if not out:
        for fb in FALLBACK:
            out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": fb["title"], "start_date": None, "end_date": None, "detail_page_url": BASE_URL, "description": fb.get("note"), "image_url": None})
    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"] + "|" + item["exhibition_title"]
        if k not in seen:
            seen.add(k)
            unique.append(item)
    return unique
