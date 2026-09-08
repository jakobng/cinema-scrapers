#!/usr/bin/env python3
# act_one_module.py
# Scraper for ActOne Cinema & Cafe (Acton)
# https://actonecinema.co.uk/ActOneCinema.dll/WhatsOn
#
# Data source: the `var Events = {...}` JSON blob embedded in every Savoy
# Systems page of the site. It carries the full programme (events + every
# performance date/time/booking link), so one GET is enough — no JS needed.
#
# The cinema previously ran on Indy Systems and exposed a /graphql endpoint;
# that has been retired and now 302-redirects, hence this rewrite.

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

BASE_URL = "https://actonecinema.co.uk"
DLL_URL = f"{BASE_URL}/ActOneCinema.dll/"
SCHEDULE_URL = f"{DLL_URL}WhatsOn"
CINEMA_NAME = "ActOne Cinema & Cafe"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14

# Non-screening programme strands that share the same feed (quiz nights, gigs).
SKIP_TYPE_DESCRIPTIONS = {"live music", "fun in the lounge"}

# Per-performance "Y"/"N" flags, in the order the site's own event key lists them.
PERFORMANCE_FLAGS = [
    ("CC", "Captioned"),
    ("AD", "Audio Described"),
    ("SF", "SEND Friendly"),
    ("C1", "ClassicOne Cinema Club"),
    ("CB", "Carers & Babies"),
    ("SB", "Subtitled"),
    ("DB", "Dubbed"),
    ("QA", "Q+A"),
    ("ES", "Exhibition On Screen"),
    ("RR", "Rerelease"),
    ("RS", "Restoration"),
    ("FP", "Footprints"),
    ("FF", "Family Friendly"),
    ("NA", "No Ads/Trailers"),
]

EVENTS_RE = re.compile(r"var\s+Events\s*=\s*(\{)", re.I)


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip())


def _unescape(value):
    """The Events blob is HTML-escaped inside the page, so undo that post-parse."""
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, list):
        return [_unescape(v) for v in value]
    if isinstance(value, dict):
        return {k: _unescape(v) for k, v in value.items()}
    return value


def _extract_events(page_html: str) -> List[Dict]:
    """Pull the `var Events = {...}` object out of the page and parse it."""
    match = EVENTS_RE.search(page_html)
    if not match:
        raise ValueError("Could not find the `var Events` block in the ActOne page.")

    start = match.start(1)
    depth = 0
    end = None
    # ponytail: brace counting rather than a JS parser. Safe here because the
    # blob is machine-generated JSON with all quotes/braces properly escaped.
    for i in range(start, len(page_html)):
        char = page_html[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("Unterminated `var Events` block in the ActOne page.")

    payload = json.loads(page_html[start:end])
    return _unescape(payload).get("Events") or []


def _parse_date(value: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(_clean(value))
    except (TypeError, ValueError):
        return None


def _parse_time(performance: Dict) -> Optional[str]:
    """Prefer the zero-padded HHMM field, fall back to the display string."""
    raw = _clean(performance.get("StartTime"))
    match = re.fullmatch(r"(\d{1,2})(\d{2})", raw)
    if not match:
        match = re.match(r"(\d{1,2}):(\d{2})", _clean(performance.get("StartTimeAndNotes")))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return f"{hour:02d}:{minute:02d}"


def _format_tags(performance: Dict) -> List[str]:
    return [label for key, label in PERFORMANCE_FLAGS if performance.get(key) == "Y"]


def _runtime(value) -> str:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return ""
    return str(minutes) if minutes > 0 else ""


def _year(value) -> str:
    match = re.search(r"(19|20)\d{2}", _clean(value))
    return match.group(0) if match else ""


def scrape_act_one_cinema() -> List[Dict]:
    """
    Scrape ActOne Cinema showtimes from the Savoy Systems "What's On" page.

    Returns a list of showtime records with standard schema.
    """
    shows = []

    try:
        resp = requests.get(SCHEDULE_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        events = _extract_events(resp.text)
        print(f"[{CINEMA_NAME}] Found {len(events)} programme entries", file=sys.stderr)

        window_end = TODAY + dt.timedelta(days=WINDOW_DAYS)

        for event in events:
            if _clean(event.get("TypeDescription")).lower() in SKIP_TYPE_DESCRIPTIONS:
                continue

            title = _clean(event.get("Title"))
            if not title:
                continue

            detail_url = _clean(event.get("URL"))
            synopsis = _clean(event.get("Synopsis"))
            director = _clean(event.get("Director"))
            country = _clean(event.get("Country"))
            year = _year(event.get("Year"))
            runtime_min = _runtime(event.get("RunningTime"))

            for performance in event.get("Performances") or []:
                show_date = _parse_date(performance.get("StartDate"))
                if not show_date or not (TODAY <= show_date < window_end):
                    continue

                showtime = _parse_time(performance)
                if not showtime:
                    continue

                booking_url = _clean(performance.get("URL"))
                if booking_url:
                    booking_url = urljoin(DLL_URL, booking_url)

                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": title,
                    "movie_title_en": title,
                    "date_text": show_date.isoformat(),
                    "showtime": showtime,
                    "detail_page_url": detail_url,
                    "booking_url": booking_url,
                    "director": director,
                    "year": year,
                    "country": country,
                    "runtime_min": runtime_min,
                    "synopsis": synopsis[:500] if synopsis else "",
                    "format_tags": _format_tags(performance),
                })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    # Deduplicate
    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_act_one_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
