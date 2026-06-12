# Castlefield Gallery, Manchester
from urllib.parse import urljoin
import re
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.castlefieldgallery.co.uk"
EXHIBITIONS_URL = "https://www.castlefieldgallery.co.uk/event-type/exhibition/"
VENUE_NAME = "Castlefield Gallery"
VENUE_CITY = "Manchester"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def scrape_castlefield():
    out = []
    try:
        r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch Castlefield: " + str(e)) from e

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/event/" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        title = norm(a.get_text())
        if not title or len(title) < 3:
            continue
        if title.lower() in ("exhibition", "back to top", "we are always", "free to visit"):
            continue
        date_text = ""
        parent = a.parent
        for _ in range(6):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            parent = parent.parent
        start_str, end_str = parse_date_range(date_text)
        m = re.search(r"(\d{1,2})\.(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.(\d{2})\s*-\s*(\d{1,2})\.(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.(\d{2})", date_text, re.I)
        if m and not start_str:
            months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
            try:
                d1, mo1, y1, d2, mo2, y2 = m.groups()
                mo1 = months.index(mo1.lower()) + 1
                mo2 = months.index(mo2.lower()) + 1
                yy1 = "20" + y1 if len(y1) == 2 else y1
                yy2 = "20" + y2 if len(y2) == 2 else y2
                start_str = f"{yy1}-{mo1:02d}-{int(d1):02d}"
                end_str = f"{yy2}-{mo2:02d}-{int(d2):02d}"
            except (ValueError, IndexError):
                pass
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
