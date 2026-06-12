# National Museums Liverpool (Walker, Lady Lever, Sudley House, World Museum,
# Museum of Liverpool) via the Drupal JSON:API that backs liverpoolmuseums.org.uk.
# The public site is client-rendered, so HTML scraping no longer works.
import threading
from datetime import date, timedelta

import requests

API_URL = "https://content.liverpoolmuseums.org.uk/jsonapi/node/exhibition"
SITE_BASE = "https://www.liverpoolmuseums.org.uk"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "application/vnd.api+json",
}
TIMEOUT = 25

# venue code -> (venue name, city)
VENUES = {
    "wa": ("Walker Art Gallery", "Liverpool"),
    "ll": ("Lady Lever Art Gallery", "Port Sunlight"),
    "sh": ("Sudley House", "Liverpool"),
    "wm": ("World Museum", "Liverpool"),
    "ml": ("Museum of Liverpool", "Liverpool"),
}

_cache_lock = threading.Lock()
_cache = {"rows": None}


def _fetch_all_exhibitions():
    """Fetch recent exhibition nodes (2 pages of 50, newest first). Cached so
    the per-venue scrape functions share one set of API calls."""
    with _cache_lock:
        if _cache["rows"] is not None:
            return _cache["rows"]
        rows = []
        url = API_URL + "?page%5Blimit%5D=50&sort=-field_date.value"
        for _ in range(2):
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            rows.extend(payload.get("data", []))
            url = (payload.get("links", {}).get("next") or {}).get("href")
            if not url:
                break
        _cache["rows"] = rows
        return rows


def _scrape_venue(code):
    venue_name, venue_city = VENUES[code]
    today = date.today()
    cutoff = (today - timedelta(days=21)).isoformat()
    out = []
    for node in _fetch_all_exhibitions():
        attrs = node.get("attributes", {})
        if attrs.get("field_venue_code") != code or not attrs.get("status", True):
            continue
        title = (attrs.get("title") or "").strip()
        if not title:
            continue
        dates = attrs.get("field_date") or {}
        start = dates.get("value")
        end = dates.get("end_value")
        if end and end < cutoff:
            continue
        # Displays running for many years are permanent galleries, not exhibitions
        if start and end and (int(end[:4]) - int(start[:4])) > 4:
            continue
        # No end date and started long ago = semi-permanent display; keep as ongoing
        alias = (attrs.get("path") or {}).get("alias") or ""
        out.append({
            "venue_name": venue_name,
            "venue_city": venue_city,
            "exhibition_title": title[:500],
            "start_date": start,
            "end_date": end,
            "detail_page_url": SITE_BASE + alias if alias else SITE_BASE,
            "description": (attrs.get("field_summary") or None),
            "image_url": None,  # filled by detail-page og:image enrichment
        })
    return out


def scrape_walker_art_gallery():
    return _scrape_venue("wa")


def scrape_lady_lever():
    return _scrape_venue("ll")


def scrape_sudley_house():
    return _scrape_venue("sh")


def scrape_world_museum():
    return _scrape_venue("wm")


def scrape_museum_of_liverpool():
    return _scrape_venue("ml")
