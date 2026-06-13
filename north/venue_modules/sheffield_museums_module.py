# Sheffield Museums (Millennium Gallery, Graves Gallery, Weston Park Museum) - exhibitions
#
# The public /whats-on listing is client-rendered (JS) and mixes exhibitions with
# events/workshops, so it is unusable for a static scrape. Each venue's /visit-us/<venue>
# page, however, is server-rendered and presents its current exhibitions as
# "smt-media-50" blocks: a real entry image, an <h3> title, a <strong> date line
# ("12 Jun - 13 Sep 2026", "Until 29 Nov 2026", "Continuing Display", ...), a
# "Free Exhibition" tag, and a "Find out more" link to /whats-on/<slug>/.
#
# We parse those blocks directly. Nav/promo blocks ("Hire ...", "See more next door")
# carry no /whats-on/ link and are dropped automatically.
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from ._utils import norm

BASE_URL = "https://www.sheffieldmuseums.org.uk"
VENUE_NAME = "Sheffield Museums"
VENUE_CITY = "Sheffield"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

# Venue landing pages that server-render current exhibitions.
VENUE_PAGES = [
    "/visit-us/millennium-gallery",
    "/visit-us/graves-gallery",
    "/visit-us/weston-park-museum",
]

# A real exhibition detail link, e.g. /whats-on/the-football-art-prize-2026/
DETAIL_RE = re.compile(r"/whats-on/[a-z0-9][a-z0-9-]+/?$", re.IGNORECASE)
# Date line phrasings that mean "no fixed run" -> leave dates blank (ongoing).
PERMANENT_RE = re.compile(r"continuing display|now open|permanent|ongoing|daily", re.IGNORECASE)
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _one_date(text, default_year=None):
    """Parse a single 'DD Mon[ YYYY]' fragment to (year, month, day) or None."""
    if not text:
        return None
    # Repair missing space between month and year, e.g. "1 Nov2026".
    text = re.sub(r"([A-Za-z])(\d{4})", r"\1 \2", text)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,})\.?\s*(\d{4})?", text)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2)[:3].lower())
    if not month:
        return None
    year = int(m.group(3)) if m.group(3) else default_year
    if not year:
        return None
    return (year, month, day)


def _iso(parts):
    return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}" if parts else None


def _parse_date_line(text):
    """Return (start_iso, end_iso) from a Sheffield date strong, either may be None."""
    if not text:
        return None, None
    t = norm(text.replace("\xa0", " "))
    # Drop a trailing "| Venue Name" suffix if the date shares the strong.
    t = t.split("|")[0].strip()
    if not t or PERMANENT_RE.search(t):
        return None, None
    low = t.lower()
    if low.startswith("until"):
        return None, _iso(_one_date(t))
    if low.startswith("from"):
        return _iso(_one_date(t)), None
    parts = re.split(r"\s*[–—-]\s*", t, maxsplit=1)
    if len(parts) == 2:
        end = _one_date(parts[1])
        start = _one_date(parts[0], default_year=end[0] if end else None)
        return _iso(start), _iso(end)
    one = _one_date(t)
    return _iso(one), _iso(one)


def _detail_link(block):
    for a in block.find_all("a", href=True):
        if DETAIL_RE.search(a.get("href", "")):
            return urljoin(BASE_URL, a["href"])
    return None


def scrape_sheffield_museums():
    out = []
    seen = set()
    for path in VENUE_PAGES:
        try:
            r = requests.get(BASE_URL + path, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for block in soup.find_all("div", class_="smt-media-50"):
            detail_url = _detail_link(block)
            if not detail_url or detail_url in seen:
                continue
            inner = block.find(class_="smt-media-50-copy-inner") or block
            heading = inner.find(["h1", "h2", "h3", "h4"])
            title = norm(heading.get_text()) if heading else ""
            if not title or len(title) < 3:
                continue

            strongs = inner.find_all("strong")
            start_str, end_str = _parse_date_line(strongs[0].get_text() if strongs else "")

            img = block.find("img")
            image_url = urljoin(BASE_URL, img["src"]) if img and img.get("src") else None

            # First paragraph after the date/tag lines is the blurb, if present.
            desc = None
            for p in inner.find_all("p"):
                ptxt = norm(p.get_text(" "))
                if ptxt and not p.find("strong") and "Please Donate" not in ptxt:
                    desc = ptxt[:1000]
                    break

            seen.add(detail_url)
            out.append({
                "venue_name": VENUE_NAME,
                "venue_city": VENUE_CITY,
                "exhibition_title": title[:500],
                "start_date": start_str,
                "end_date": end_str,
                "detail_page_url": detail_url,
                "description": desc,
                "image_url": image_url,
            })
    return out


if __name__ == "__main__":
    for row in scrape_sheffield_museums():
        print(f"{'Y' if row['image_url'] else '-'} {str(row['start_date']):>10} .. {str(row['end_date']):<10} | {row['exhibition_title'][:45]}")
