# Hatton Gallery, Newcastle University
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://hattongallery.org.uk"
WHATS_ON_URL = "https://hattongallery.org.uk/whats-on"
VENUE_NAME = "Hatton Gallery"
VENUE_CITY = "Newcastle"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def _slug_to_title(slug):
    if not slug:
        return ""
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def scrape_hatton():
    out = []
    try:
        r = requests.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch " + WHATS_ON_URL + ": " + str(e)) from e

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/whats-on/" not in href or href == "/whats-on" or href.rstrip("/") == "/whats-on":
            continue
        full_url = urljoin(BASE_URL, href)
        path = href.split("?")[0].rstrip("/")
        slug = path.split("/whats-on/")[-1].strip("/") if "/whats-on/" in path else ""
        if not slug:
            continue
        title = norm(a.get_text()) or _slug_to_title(slug)
        if not title or len(title) < 3:
            title = _slug_to_title(slug)
        if title.lower() in ("what's on", "view all", "back to what's on"):
            continue
        date_text = ""
        parent = a.parent
        for _ in range(6):
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
