#!/usr/bin/env python3
# Yorkshire Sculpture Park - exhibitions scraper

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import parse_date_range, parse_short_date_range, norm

# Strip "Now showing"/"Upcoming" and leading date block to get exhibition title
YSP_TITLE_CLEAN_RE = re.compile(
    r"^(?:Now showing|Upcoming)\s+"
    r"(?:"
    r"(?:Sat|Sun|Mon|Tue|Wed|Thu|Fri)\s+\d{1,2}\s+"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+\d{4})?)?\s*[–\-]\s*"
    r"(?:(?:Sat|Sun|Mon|Tue|Wed|Thu|Fri)\s+)?\d{1,2}\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}"
    r"|(?:From|Summer)\s+\d{1,4}(?:\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))?\s*\d{4}"
    r")\s*",
    re.IGNORECASE,
)

BASE_URL = "https://ysp.org.uk"
EXHIBITIONS_URL = f"{BASE_URL}/exhibitions"

VENUE_NAME = "Yorkshire Sculpture Park"
VENUE_CITY = "West Bretton"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


def scrape_ysp():
    """Return list of exhibition dicts for Yorkshire Sculpture Park."""
    out = []
    try:
        r = requests.get(EXHIBITIONS_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {EXHIBITIONS_URL}: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or "/exhibitions/" not in href:
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url.rstrip("/") == EXHIBITIONS_URL.rstrip("/"):
            continue
        if "/past-exhibitions" in href or href.rstrip("/").endswith("/past-exhibitions"):
            continue
        raw_title = norm(a.get_text())
        if not raw_title or len(raw_title) < 3:
            continue
        if raw_title.lower() in ("read more", "exhibitions", "view all"):
            continue
        # Strip "Now showing"/"Upcoming" and date block; take first sentence or 120 chars
        title = YSP_TITLE_CLEAN_RE.sub("", raw_title).strip()
        if not title:
            title = raw_title
        title = re.sub(r"^(?:Now showing|Upcoming)\s+", "", title, flags=re.IGNORECASE).strip()
        # Trim to first sentence or reasonable length
        for sep in (". ", " will ", " is ", " features ", " brings ", " showcases "):
            if sep in title:
                title = title.split(sep)[0].strip()
                break
        if len(title) > 120:
            title = title[:117].rsplit(" ", 1)[0] + "..." if " " in title[:117] else title[:120]
        title = title or raw_title[:500]

        # Dates live on the card itself in short year-less form
        # ("Sat 14 Mar – Sun 7 Feb"); never walk up to page level, where a
        # stray unrelated date would be applied to every card.
        anchor_text = norm(a.get_text(" "))
        start_str, end_str = parse_short_date_range(anchor_text)
        if not (start_str or end_str):
            start_str, end_str = parse_date_range(anchor_text)
            if start_str and start_str == end_str:
                start_str, end_str = None, None
        if not (start_str or end_str):
            m = re.search(
                r"From\s+(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
                anchor_text, re.IGNORECASE)
            if m:
                from datetime import date as _date
                from ._utils import MONTH_MAP
                try:
                    start_str = _date(int(m.group(3)), MONTH_MAP[m.group(2).capitalize()], int(m.group(1))).isoformat()
                except (ValueError, KeyError):
                    pass

        # Strip trailing date fragments left in the title
        title = re.sub(
            r"\s+(?:From\s+\d{1,2}\s+\w+|(?:Sat|Sun|Mon|Tue|Wed|Thu|Fri)[a-z]*\s+\d{1,2}\s+\w+|Summer\s+\d{4}).*$",
            "", title, flags=re.IGNORECASE).strip() or title
        title = re.sub(
            r"\s+(?:Sat|Sun|Mon|Tue|Wed|Thu|Fri)[a-z]*\s+\d{1,2}\s*[–\-]?\s*$",
            "", title, flags=re.IGNORECASE).strip() or title

        out.append({
            "venue_name": VENUE_NAME,
            "venue_city": VENUE_CITY,
            "exhibition_title": title[:500] if len(title) > 500 else title,
            "start_date": start_str,
            "end_date": end_str,
            "detail_page_url": full_url,
            "description": None,
            "image_url": None,
        })

    seen = set()
    unique = []
    for item in out:
        key = item["detail_page_url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique
