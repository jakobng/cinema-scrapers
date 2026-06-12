# Danum Gallery, Library and Museum (DGLAM), Doncaster
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.doncaster.gov.uk"
WHATSON_URL = "https://www.doncaster.gov.uk/services/culture-leisure-tourism/danum-gallery-library-and-museum-dglam"
VENUE_NAME = "Danum Gallery, Library and Museum"
VENUE_CITY = "Doncaster"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def scrape_danum():
    out = []
    try:
        r = requests.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch Danum: " + str(e)) from e

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/whats-on" not in href.lower() and "/event" not in href.lower() and "/exhibition" not in href.lower():
            continue
        full_url = urljoin(BASE_URL, href)
        title = norm(a.get_text())
        if not title or len(title) < 3:
            continue
        if title.lower() in ("what's on", "danum", "visit"):
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

    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(item)
    return unique
