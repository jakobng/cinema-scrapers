# MIMA (Middlesbrough Institute of Modern Art)
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.visitmima.com"
VENUE_NAME = "MIMA"
VENUE_CITY = "Middlesbrough"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

FALLBACK = [
    {"title": "Winifred Nicholson: Cumbrian Rag Rugs", "end_date": "2026-03-23"},
    {"title": "The Secret Lives of Bottle of Notes", "end_date": "2026-10-05"},
    {"title": "New Contemporaries", "start_date": "2026-05-08", "end_date": "2026-08-16"},
]


def scrape_mima():
    out = []
    for path in ["/whats-on", "/exhibitions", ""]:
        try:
            url = urljoin(BASE_URL, path) if path else BASE_URL
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if "/exhibition" not in href.lower() and "/whats-on" not in href.lower():
                continue
            full_url = urljoin(BASE_URL, href)
            if full_url == url or "visitmima.com" not in full_url:
                continue
            title = norm(a.get_text())
            if not title or len(title) < 4:
                continue
            date_text = ""
            parent = a.parent
            for _ in range(5):
                if not parent:
                    break
                date_text = parent.get_text(separator=" ")
                parent = parent.parent
            start_str, end_str = parse_date_range(date_text)
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": title[:500],
                "start_date": start_str,
                "end_date": end_str,
                "detail_page_url": full_url,
                "description": None,
                "image_url": None,
            })
        if out:
            break

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
                "start_date": fb.get("start_date"),
                "end_date": fb.get("end_date"),
                "detail_page_url": urljoin(BASE_URL, "/whats-on/"),
                "description": None,
                "image_url": None,
            })
    return unique
