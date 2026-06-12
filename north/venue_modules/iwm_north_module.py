# IWM North, Manchester
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.iwm.org.uk"
WHATS_ON_URL = "https://www.iwm.org.uk/visits/iwm-north/whats-on"
VENUE_NAME = "IWM North"
VENUE_CITY = "Manchester"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

def scrape_iwm_north():
    out = []
    try:
        r = requests.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch: " + str(e)) from e
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/events/" not in href and "/visits/iwm-north" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url.rstrip("/").endswith("whats-on"):
            continue
        title = norm(a.get_text())
        if not title or len(title) < 3:
            continue
        if title.lower() in ("read more", "book", "what's on", "filter by"):
            continue
        date_text = ""
        p = a.parent
        for _ in range(6):
            if not p:
                break
            date_text = p.get_text(separator=" ")
            p = p.parent
        start_str, end_str = parse_date_range(date_text)
        out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": title[:500], "start_date": start_str, "end_date": end_str, "detail_page_url": full_url, "description": None, "image_url": None})
    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"]
        if k not in seen:
            seen.add(k)
            unique.append(item)
    return unique
