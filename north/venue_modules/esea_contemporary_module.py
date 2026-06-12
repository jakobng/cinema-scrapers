# esea contemporary (formerly CFCCA), Manchester - East & Southeast Asian art
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://www.eseacontemporary.org"
VENUE_NAME = "esea contemporary"
VENUE_CITY = "Manchester"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

# Nav, footer and non-exhibition link text to exclude
SKIP_TITLES = {
    "visit", "about", "read more", "exhibitions", "events", "projects",
    "online archives", "learn & engage", "learn and engage", "residencies",
    "esea artclub", "esea showcase", "news", "shop", "donate",
    "privacy & cookies", "privacy and cookies", "cookies", "terms and conditions",
    "terms of use", "learn more", "venue hire", "keep reading...",
    "contact", "accessibility", "get in touch", "opportunities",
    "instagram", "facebook", "tiktok", "youtube", "press@", "hire@", "hello@",
}
# Only keep links that look like exhibition/programme pages
EXHIBITION_PATH_PREFIXES = ("/exhibitions/", "/programme/", "/event/", "/whats-on/")


def scrape_esea_contemporary():
    out = []
    for path in ["/exhibitions", "/programme", "/", "/whats-on"]:
        from_home = path == "/"
        try:
            r = requests.get(BASE_URL + path, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or not (href.startswith("/") or "eseacontemporary" in href):
                continue
            full_url = urljoin(BASE_URL, href)
            if full_url == BASE_URL + "/" or full_url.rstrip("/") == BASE_URL:
                continue
            if from_home and not any(p in full_url for p in EXHIBITION_PATH_PREFIXES):
                continue
            title = norm(a.get_text())
            if not title or len(title) < 3:
                continue
            title_lower = title.lower()
            if title_lower in SKIP_TITLES:
                continue
            if any(skip in title_lower for skip in ("@", "privacy", "cookies", "terms", "instagram", "facebook", "tiktok", "youtube")):
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
        FALLBACK = [
            {"title": "Voicing the Archive", "slug": "voicing-the-archive"},
            {"title": "30 Years of CFCCA", "slug": "30-years-of-cfcca"},
        ]
        for fb in FALLBACK:
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": fb["title"],
                "start_date": None,
                "end_date": None,
                "detail_page_url": urljoin(BASE_URL, "/exhibitions/" + fb["slug"]) if fb.get("slug") else BASE_URL,
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
