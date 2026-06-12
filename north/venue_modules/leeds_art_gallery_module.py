# Leeds Art Gallery
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://museumsandgalleries.leeds.gov.uk"
VENUE_NAME = "Leeds Art Gallery"
VENUE_CITY = "Leeds"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25
FALLBACK = [
    {"title": "Nocturnes and Atkinson Grimshaw", "start_date": "2025-11-14", "end_date": "2026-04-19"},
    {"title": "Plant Dreaming", "start_date": "2025-11-14", "end_date": "2026-04-19"},
    {"title": "Portrayals of Women", "start_date": "2025-03-29", "end_date": "2026-04-05"},
]

def scrape_leeds_art_gallery():
    out = []
    for path in ["/whats-on", "/pQw11hQ/exhibitions", "/"]:
        try:
            r = requests.get(BASE_URL + path, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 403:
                continue
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            full_url = urljoin(BASE_URL, href)
            if "/exhibition" not in full_url and "/plant-dreaming" not in full_url and "/portrayals" not in full_url and "/pQ" not in full_url:
                continue
            title = norm(a.get_text())
            if not title or len(title) < 4 or title.lower() in ("read more", "exhibitions", "what's on"):
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
        if out:
            break
    if not out:
        for fb in FALLBACK:
            out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": fb["title"], "start_date": fb.get("start_date"), "end_date": fb.get("end_date"), "detail_page_url": BASE_URL + "/leeds-art-gallery", "description": None, "image_url": None})
    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(item)
    return unique
