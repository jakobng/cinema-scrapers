from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

CINEMA_NAME = "Koenji Cinema Club"
EVENT_URL = "https://www.meetup.com/koenji-cinema-club/"
VENUE = "The Den, Koenji"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en,ja;q=0.8"}

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _today_jst() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _parse_event_datetime(text: str, today: dt.date) -> tuple[str, str] | None:
    pattern = re.compile(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
        r"([A-Za-z]{3,9})\s+(\d{1,2})\s+·\s+"
        r"(\d{1,2}):(\d{2})\s*(AM|PM)\s+JST",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    month_name, day_raw, hour_raw, minute, ampm = match.groups()
    month = MONTHS.get(month_name[:3].lower())
    if not month:
        return None
    hour = int(hour_raw)
    if ampm.upper() == "PM" and hour != 12:
        hour += 12
    if ampm.upper() == "AM" and hour == 12:
        hour = 0
    year = today.year
    date_value = dt.date(year, month, int(day_raw))
    if date_value < today - dt.timedelta(days=45):
        date_value = dt.date(year + 1, month, int(day_raw))
    return date_value.isoformat(), f"{hour:02d}:{minute}"


def _clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    date_marker = re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+[A-Za-z]{3,9}\s+\d{1,2}\s+·", text)
    if date_marker:
        text = text[:date_marker.start()].strip()
    text = re.sub(r"^¥?[\d,.]+\.?\d*\s*", "", text)
    return text


def scrape_koenji_cinema_club() -> List[Dict[str, str]]:
    try:
        response = requests.get(EVENT_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"ERROR: [{CINEMA_NAME}] Could not fetch {EVENT_URL}: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    today = _today_jst()
    listings: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.select("a[href]"):
        text = anchor.get_text(" ", strip=True)
        parsed = _parse_event_datetime(text, today)
        if not parsed:
            continue
        date_text, showtime = parsed
        if dt.date.fromisoformat(date_text) < today:
            continue
        title = _clean_title(text)
        if not title:
            title = "Koenji Cinema Club screening"
        detail_url = anchor.get("href") or EVENT_URL
        if detail_url.startswith("/"):
            detail_url = f"https://www.meetup.com{detail_url}"
        key = (title, date_text, showtime)
        if key in seen:
            continue
        seen.add(key)
        listings.append({
            "cinema_name": CINEMA_NAME,
            "cinema_address": "4-25-8 Koenjiminami, Suginami City, Tokyo",
            "cinema_site_url": EVENT_URL,
            "movie_title": title,
            "date_text": date_text,
            "showtime": showtime,
            "detail_page_url": detail_url,
            "program_title": VENUE,
            "synopsis": text,
        })

    if not listings:
        print(f"INFO: [{CINEMA_NAME}] No upcoming public Meetup screenings found.")
    return listings


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    data = scrape_koenji_cinema_club()
    print(f"Collected {len(data)} listings.")
