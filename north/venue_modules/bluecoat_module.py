# Bluecoat, Liverpool - exhibitions
# The /whatson listing mixes exhibitions with workshops, markets, tours and
# events. Each c-grid__item card carries a type label (.text-brand-blue) -
# "Exhibition", "Workshop", "Fair/Market", ... - so we keep only Exhibitions.
# The card also holds the title, a weekday-prefixed date range, and an image;
# images are lazy placeholders here, so they're left for the detail-page
# enrichment pass to fill from og:image.
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import norm, parse_uk_date_text

BASE_URL = "https://www.thebluecoat.org.uk"
WHATSON_URL = "https://www.thebluecoat.org.uk/whatson"
VENUE_NAME = "Bluecoat"
VENUE_CITY = "Liverpool"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)", "Accept-Language": "en-GB,en;q=0.9"}
TIMEOUT = 25

_WEEKDAY_RE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", re.IGNORECASE)
# A date range/open-ended date as written in the card, after weekday stripping.
_DATE_RE = re.compile(
    r"\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?\s*[–—-]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|(?:from|until)\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}",
    re.IGNORECASE,
)


def scrape_bluecoat():
    try:
        r = requests.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch Bluecoat: " + str(e)) from e

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    seen = set()
    for card in soup.select("div.c-grid__item"):
        a = card.find("a", href=lambda h: h and "/whatson/" in h and h.rstrip("/") != "/whatson")
        if not a:
            continue
        type_el = card.select_one(".text-brand-blue")
        if not type_el or type_el.get_text(strip=True).lower() != "exhibition":
            continue
        detail_url = urljoin(BASE_URL, a["href"].split("?")[0])
        if detail_url in seen:
            continue

        heading = card.find(["h2", "h3", "h4"])
        title = norm(heading.get_text()) if heading else norm(a.get_text())
        if not title or len(title) < 3:
            continue

        card_text = _WEEKDAY_RE.sub("", norm(card.get_text(" ")))
        m = _DATE_RE.search(card_text)
        start_str, end_str = parse_uk_date_text(m.group(0)) if m else (None, None)

        seen.add(detail_url)
        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500],
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": detail_url,
            "description": None,
            "image_url": None,  # lazy-loaded on the listing; filled by enrichment
        })
    return out


if __name__ == "__main__":
    for r in scrape_bluecoat():
        print(f"{str(r['start_date']):>10}..{str(r['end_date']):<10} | {r['exhibition_title'][:50]}")
