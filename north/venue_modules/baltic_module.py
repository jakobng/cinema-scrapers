# Baltic Centre for Contemporary Art, Gateshead (whats-on is JS-heavy; we try scrape then fallback)
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://baltic.art"
WHATS_ON_URL = "https://baltic.art/whats-on"
VENUE_NAME = "Baltic Centre for Contemporary Art"
VENUE_CITY = "Gateshead"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

# Strip venue name and trailing date/cruft from link text (no space before "Baltic" in some markup)
BALTIC_VENUE_RE = re.compile(r"Baltic Centre for Contemporary Art.*$", re.I)

def _slug_to_title(slug):
    if not slug:
        return ""
    return " ".join(w.capitalize() for w in slug.split("-"))


FALLBACK = [
    {"title": "For All At Last Return", "slug": "for-all-at-last-return", "end_date": "2026-06-07"},
    {"title": "Saelia Aparicio: A Joyful Parasite", "slug": "saelia-aparicio-a-joyful-parasite", "end_date": "2026-03-08"},
]

def scrape_baltic():
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
        if "/whats-on/" not in href or href == "/whats-on" or href == "/whats-on/":
            continue
        full_url = urljoin(BASE_URL, href)
        path = href.split("?")[0].rstrip("/")
        slug = path.split("/whats-on/")[-1].strip("/") if "/whats-on/" in path else ""
        link_text = norm(a.get_text())
        if not link_text or len(link_text) < 3:
            continue
        if link_text.lower() in ("see more", "what's on", "discover what's on"):
            continue
        title = norm(BALTIC_VENUE_RE.sub("", link_text))
        if not title and slug:
            title = _slug_to_title(slug)
        elif not title:
            title = link_text
        if len(title) > 120 and slug:
            title = _slug_to_title(slug)
        date_text = ""
        parent = a.parent
        for _ in range(5):
            if not parent:
                break
            date_text = parent.get_text(separator=" ")
            parent = parent.parent
        start_str, end_str = parse_date_range(date_text)
        out.append({"venue_name": VENUE_NAME, "venue_city": VENUE_CITY, "exhibition_title": title[:500], "start_date": start_str, "end_date": end_str, "detail_page_url": full_url, "description": None, "image_url": None})
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
                "end_date": fb.get("end_date"),
                "detail_page_url": urljoin(BASE_URL, "/whats-on/" + fb["slug"] + "/"),
                "description": None,
                "image_url": None,
            })
    return unique
