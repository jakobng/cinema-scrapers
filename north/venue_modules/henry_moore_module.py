# Henry Moore Institute, Leeds
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://henry-moore.org"
WHATS_ON_URL = "https://henry-moore.org/henry-moore-institute/whats-on-henry-moore-institute"
VENUE_NAME = "Henry Moore Institute"
VENUE_CITY = "Leeds"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25


def scrape_henry_moore():
    out = []
    try:
        r = requests.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch Henry Moore Institute: " + str(e)) from e

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/whats-on/" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        title = norm(a.get_text())
        if not title or len(title) < 4:
            continue
        if title.lower() in ("learn more", "book your free ticket", "exhibition", "guided tour", "library display"):
            continue
        if "Part of " in title or "Session for " in title:
            continue
        date_text = ""
        parent = a.parent
        for _ in range(6):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            parent = parent.parent
        # Skip event-type entries: single-date events get wrong end date
        dt_lower = date_text.lower()
        if any(x in dt_lower for x in ("every tuesday", "every thursday", "book your", "guided tour", "lecture", "performance", "family-friendly workshop", "artist in conversation", "teacher cpd")):
            continue
        start_str, end_str = parse_date_range(date_text)
        if "Permanent" in date_text or "permanent" in date_text:
            end_str = None
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
