# Bluecoat, Liverpool
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.thebluecoat.org.uk"
WHATSON_URL = "https://www.thebluecoat.org.uk/whatson"
VENUE_NAME = "Bluecoat"
VENUE_CITY = "Liverpool"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def scrape_bluecoat():
    out = []
    try:
        r = requests.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch Bluecoat: " + str(e)) from e

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/whatson/" not in href or href.rstrip("/") == "/whatson":
            continue
        full_url = urljoin(BASE_URL, href)
        link_text = norm(a.get_text())
        if not link_text or len(link_text) < 3:
            continue
        if link_text.lower() in ("exhibition", "what's on", "explore all digital projects"):
            continue
        parent = a.parent
        date_text = ""
        for _ in range(5):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            parent = parent.parent
        start_str, end_str = parse_date_range(date_text)
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": link_text[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": full_url,
            "description": None,
            "image_url": None,
        })

    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(item)
    return unique
