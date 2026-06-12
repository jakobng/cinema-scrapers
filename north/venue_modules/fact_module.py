#!/usr/bin/env python3
# FACT, Liverpool - exhibitions

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ._utils import norm

BASE_URL = "https://www.fact.co.uk"
WHATS_ON_URL = "https://www.fact.co.uk/whats-on"
VENUE_NAME = "FACT"
VENUE_CITY = "Liverpool"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NorthArtExhibitions/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 25


# Range: "19 Jan 26 — 22 Mar 26" or "19 Jan 26 - 22 Mar 26"
_DATE_RANGE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{2})\s*[-\u2014]\s*(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{2})",
    re.I,
)
# Single: "19 Mar 26" (start = end)
_DATE_SINGLE = re.compile(
    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{2})",
    re.I,
)
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def _parse_fact_date(text):
    """Return (start_iso, end_iso) or (None, None). Handles range and single date."""
    m = _DATE_RANGE.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        try:
            yy1, yy2 = "20" + y1, "20" + y2
            m1 = _MONTHS.index(mo1.lower()) + 1
            m2 = _MONTHS.index(mo2.lower()) + 1
            s = yy1 + "-" + str(m1).zfill(2) + "-" + str(int(d1)).zfill(2)
            e = yy2 + "-" + str(m2).zfill(2) + "-" + str(int(d2)).zfill(2)
            return s, e
        except (ValueError, IndexError):
            pass
    m = _DATE_SINGLE.search(text)
    if m:
        d1, mo1, y1 = m.groups()
        try:
            yy = "20" + y1
            mm = _MONTHS.index(mo1.lower()) + 1
            s = yy + "-" + str(mm).zfill(2) + "-" + str(int(d1)).zfill(2)
            return s, s
        except (ValueError, IndexError):
            pass
    return None, None


def _date_for_link(link):
    """Return (start_str, end_str) from the closest ancestor of link that contains a parseable date."""
    parent = link.parent
    for _ in range(20):
        if not parent:
            break
        start_str, end_str = _parse_fact_date(parent.get_text(separator=" "))
        if start_str:
            return start_str, end_str
        parent = parent.parent
    return None, None


def scrape_fact():
    out = []
    try:
        r = requests.get(WHATS_ON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception as e:
        raise RuntimeError("Failed to fetch " + WHATS_ON_URL + ": " + str(e)) from e
    soup = BeautifulSoup(r.text, "html.parser")

    skip_titles = {"learn more", "what's on", "exhibition", "all events"}
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if ("/whats-on/" not in href and "/event/" not in href) or href in ("/whats-on", "/whats-on/"):
            continue
        full_url = urljoin(BASE_URL, href)
        title = norm(a.get_text())
        if not title or len(title) < 3:
            continue
        if title.lower() in skip_titles:
            continue
        start_str, end_str = _date_for_link(a)
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
