# The Lowry, Salford - Andrew Law Galleries exhibitions
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://thelowry.com"
WHATS_ON_URL = "https://thelowry.com/whats-on/lowry-galleries-ythl"
VENUE_NAME = "The Lowry"
VENUE_CITY = "Salford"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

FALLBACK = [
    {"title": "Modern Life: The LS Lowry Collection", "url": "https://thelowry.com/pQrPNHY/modern-life--the-ls-lowry-collection"},
    {"title": "LOWRY 360", "url": "https://thelowry.com/pQpdesN/lowry-360"},
    {"title": "The Guardians of Living Matter", "url": "https://thelowry.com/the-guardians-of-living-matter-myvx"},
    {"title": "Camille Walala: Square Eyes", "url": "https://thelowry.com/camille-walala-square-eyes-fjfq"},
]


def scrape_lowry():
    out = []
    try:
        r = requests.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        for fb in FALLBACK:
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": fb["title"],
                "start_date": None,
                "end_date": None,
                "detail_page_url": fb["url"],
                "description": None,
                "image_url": None,
            })
        return out

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href.startswith("/") or "lowry" not in href.lower():
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url == WHATS_ON_URL or "lowry-galleries" in full_url and "collection" not in full_url and "360" not in full_url and "guardians" not in full_url and "walala" not in full_url:
            continue
        title = norm(a.get_text())
        if not title or len(title) < 4:
            continue
        if title.lower() in ("shop now", "plan your visit", "book now", "zoom in", "andrew law galleries"):
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
    if not unique:
        for fb in FALLBACK:
            unique.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": fb["title"],
                "start_date": None,
                "end_date": None,
                "detail_page_url": fb["url"],
                "description": None,
                "image_url": None,
            })
    return unique
