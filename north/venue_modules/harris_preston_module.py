# The Harris, Preston (Museum, Art Gallery & Library)
# Exhibitions only: https://theharris.org.uk/whats-on/?brx_zntfbh=exhibition
from urllib.parse import urljoin
import re
import requests
from bs4 import BeautifulSoup
from ._utils import parse_date_range, norm

BASE_URL = "https://theharris.org.uk"
WHATS_ON_URL = "https://theharris.org.uk/whats-on/?brx_zntfbh=exhibition"
VENUE_NAME = "The Harris"
VENUE_CITY = "Preston"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

# Day name then comma then date (start of date part in link text)
_DAY_PATTERN = re.compile(
    r"\s*(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,.*",
    re.I,
)


def _title_from_link_text(link_text):
    """Strip 'ExhibitionFREE' and remove the date part to get exhibition title."""
    s = link_text.replace("ExhibitionFREE", "").replace("Exhibition", "").strip()
    s = _DAY_PATTERN.sub("", s).strip()
    if s.startswith("FREE "):
        s = s[5:].strip()
    return s


_MONTHS_STR = "January|February|March|April|May|June|July|August|September|October|November|December"
# Full range with two years: "24 January 2026 - Sunday, 12 April 2026"
_HARRIS_RANGE_FULL = re.compile(
    r"(\d{1,2})\s+(" + _MONTHS_STR + r")\s+(\d{4})\s*[-\u2013\u2014]\s*(\w+day)?\s*,?\s*(\d{1,2})\s+(" + _MONTHS_STR + r")\s+(\d{4})",
    re.I,
)
# Range with one year at end: "18 July – Sunday, 4 October 2026"
_HARRIS_RANGE_ONE_YEAR = re.compile(
    r"(\d{1,2})\s+(" + _MONTHS_STR + r")\s*[-\u2013\u2014]\s*(\w+day)?\s*,?\s*(\d{1,2})\s+(" + _MONTHS_STR + r")\s+(\d{4})",
    re.I,
)


def _parse_harris_date(text):
    m = _HARRIS_RANGE_FULL.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.group(1), m.group(2), m.group(3), m.group(5), m.group(6), m.group(7)
        months = _MONTHS_STR.split("|")
        try:
            m1 = months.index(mo1.capitalize()) + 1
            m2 = months.index(mo2.capitalize()) + 1
            return f"{y1}-{m1:02d}-{int(d1):02d}", f"{y2}-{m2:02d}-{int(d2):02d}"
        except (ValueError, IndexError):
            pass
    m = _HARRIS_RANGE_ONE_YEAR.search(text)
    if m:
        d1, mo1, d2, mo2, y2 = m.group(1), m.group(2), m.group(4), m.group(5), m.group(6)
        months = _MONTHS_STR.split("|")
        try:
            m1 = months.index(mo1.capitalize()) + 1
            m2 = months.index(mo2.capitalize()) + 1
            return f"{y2}-{m1:02d}-{int(d1):02d}", f"{y2}-{m2:02d}-{int(d2):02d}"
        except (ValueError, IndexError):
            pass
    return None, None


def scrape_harris_preston():
    """Scrape exhibitions only from the Harris What's On (exhibition filter)."""
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
        if "/product/" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        link_text = a.get_text(separator=" ", strip=True)
        title = norm(_title_from_link_text(link_text))
        if not title or len(title) < 2:
            continue
        date_text = link_text
        start_str, end_str = _parse_harris_date(date_text)
        if not start_str:
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
