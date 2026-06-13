# York Art Gallery scraper
#
# The /your-visit/exhibitions/ listing links each current exhibition at
# /exhibition/<slug>/ but carries no images or dates in the server HTML (those
# are JS/CSS-loaded), and the detail pages expose no og:image. Each detail page
# does, however, contain the hero image as a /wp-content/uploads/ <img> and the
# run as visible text ("until 30 August 2026"), so we fetch each detail page for
# the title, image and date.
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import norm, parse_uk_date_text

BASE_URL = "https://www.yorkartgallery.org.uk"
LISTING_URL = f"{BASE_URL}/your-visit/exhibitions/"
VENUE_NAME = "York Art Gallery"
VENUE_CITY = "York"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

DETAIL_RE = re.compile(r"/exhibition/[a-z0-9][a-z0-9-]+/?$", re.IGNORECASE)
SKIP_TITLES = {"exhibitions", "learn more", "previous", "upcoming", "read more", "find out more"}
DATE_TEXT_RE = re.compile(
    r"\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?\s*[–—-]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|(?:until|from)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}",
    re.IGNORECASE,
)


def _get_soup(url):
    """Fetch a page tolerantly. York serves real content with a 404 status, so
    we use any non-empty HTML body rather than trusting the status code."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception:
        return None
    if not r.text or len(r.text) < 500:
        return None
    return BeautifulSoup(r.text, "html.parser")


def _detail_info(url):
    """Return (title, image_url, start, end) scraped from a detail page."""
    soup = _get_soup(url)
    if soup is None:
        return None, None, None, None
    h1 = soup.find("h1")
    title = norm(h1.get_text()) if h1 else None

    image_url = None
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "/wp-content/uploads/" in src:
            image_url = urljoin(BASE_URL, src)
            break

    text = norm((soup.find("main") or soup.body or soup).get_text(" "))
    # Prefer the date written right after the title; fall back to first on page.
    window = text
    if title and title in text:
        i = text.index(title) + len(title)
        window = text[i:i + 120]
    m = DATE_TEXT_RE.search(window) or DATE_TEXT_RE.search(text)
    start_str, end_str = parse_uk_date_text(m.group(0)) if m else (None, None)
    return title, image_url, start_str, end_str


def scrape_york_art_gallery():
    # Collect unique detail links (with a fallback title from the listing anchor)
    # from the exhibitions listing, then the homepage as a backup source.
    links = {}
    for page in (LISTING_URL, BASE_URL + "/"):
        soup = _get_soup(page)
        if soup is None:
            continue
        for a in soup.find_all("a", href=DETAIL_RE):
            url = urljoin(BASE_URL, a["href"])
            listing_title = norm(a.get_text())
            if listing_title.lower() in SKIP_TITLES:
                listing_title = ""
            links.setdefault(url, listing_title)
    if not links:
        raise RuntimeError(f"No exhibition links found at {LISTING_URL}")

    out = []
    for url, listing_title in links.items():
        title, image_url, start_str, end_str = _detail_info(url)
        title = title or listing_title
        if not title or len(title) < 3:
            continue
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": url,
            "description": None,
            "image_url": image_url,
        })
    return out


if __name__ == "__main__":
    for row in scrape_york_art_gallery():
        print(f"{'IMG' if row['image_url'] else '---'} "
              f"{str(row['start_date']):>10}..{str(row['end_date']):<10} | {row['exhibition_title'][:50]}")
