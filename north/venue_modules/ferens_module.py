# Ferens Art Gallery, Hull
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.hullmuseums.co.uk"
VENUE_NAME = "Ferens Art Gallery"
VENUE_CITY = "Hull"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

# Link text that is navigation/CTA, not exhibition titles - exclude these
FERENS_NAV_BLOCKLIST = frozenset([
    "read more", "what's on", "what to see", "plan your visit", "learn with us",
    "ferens art gallery",
    "families and under 5s", "young people", "adults and communities", "find out more",
    "visit us", "get involved", "discover our latest events and exhibitions",
    "find out more about our galleries and collections",
    "visitor info and access guides to help you plan your visit",
    "explore what we offer for local schools and learners",
    "from museum trails to mini masterpieces, we have lots of fun family activities for you to enjoy",
    "discover ways to get creative, meet new friends and flex your art skills with ferens",
    "find out more about our opportunities for local artists and creatives",
    "the history of ferens art gallery", "join the team", "find out how you can support us",
    "donate now", "friends of the ferens", "general enquiry form", "directions via google maps",
    "access info and guides", "venue hire", "café", "close search", "search", "view menu", "close menu",
])

FALLBACK = [
    {"title": "Sirens: Women and the Sea", "start_date": "2025-02-14"},
    {"title": "Ferens Unpacked", "start_date": "2026-02-13"},
    {"title": "The Wonders of Moominvalley", "start_date": "2026-06-01", "end_date": "2026-09-30"},
]


def _is_nav_or_cta(title):
    if not title or len(title) < 10:
        return True
    low = title.lower().strip()
    if low in FERENS_NAV_BLOCKLIST:
        return True
    for phrase in ("plan your", "what to see", "find out more", "learn more", "read more", "what's on", "visit us", "get involved", "join the", "support us", "donate now", "guided tour"):
        if phrase in low and len(low) < 100:
            return True
    return False


def scrape_ferens():
    out = []
    for path in ["/museum-events", "/whats-on", "/ferens-art-gallery"]:
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
            if "/museum-events/" not in href and "/event/" not in href and "ferens" not in href.lower():
                continue
            full_url = urljoin(BASE_URL, href)
            title = norm(a.get_text())
            if not title or len(title) < 3:
                continue
            if _is_nav_or_cta(title):
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
            out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": fb["title"], "start_date": fb.get("start_date"), "end_date": fb.get("end_date"), "detail_page_url": BASE_URL + "/ferens-art-gallery", "description": None, "image_url": None})
    seen = set()
    unique = []
    for item in out:
        k = item["detail_page_url"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(item)
    return unique
