#!/usr/bin/env python3
# close_up_module.py
# Scraper for Close-Up Film Centre
# https://www.closeupfilmcentre.com/
#
# Structure: Concrete5 CMS with JavaScript-embedded JSON data
# Film programmes page contains a `var shows = '[...]'` JSON string

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.closeupfilmcentre.com"
FALLBACK_BASE_URL = "https://closeupfilmcentre.com"
SCHEDULE_URLS = [
    (BASE_URL, f"{BASE_URL}/film_programmes/"),
    (FALLBACK_BASE_URL, f"{FALLBACK_BASE_URL}/film_programmes/"),
]
CINEMA_NAME = "Close-Up Film Centre"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_show_datetime(show_time: str) -> Optional[tuple]:
    """
    Parse datetime string in format 'YYYY-MM-DD HH:MM:SS'.
    Returns (date, time_str) tuple or None.
    """
    if not show_time:
        return None

    try:
        parsed = dt.datetime.strptime(show_time.strip(), "%Y-%m-%d %H:%M:%S")
        return (parsed.date(), parsed.strftime("%H:%M"))
    except ValueError:
        pass

    # Try without seconds
    try:
        parsed = dt.datetime.strptime(show_time.strip(), "%Y-%m-%d %H:%M")
        return (parsed.date(), parsed.strftime("%H:%M"))
    except ValueError:
        pass

    return None


def _extract_shows_json(html: str) -> List[dict]:
    """
    Extract the 'var shows' JSON data from the page HTML.
    The data is stored as: var shows = '[{...}]';
    """
    # Look for the var shows declaration
    # Pattern: var shows = '[...]'; or var shows = "[...]";
    pattern = r"var\s+shows\s*=\s*['\"](\[.*?\])['\"]"
    match = re.search(pattern, html, re.DOTALL)

    if not match:
        # Try alternative pattern without quotes around JSON
        pattern2 = r"var\s+shows\s*=\s*(\[.*?\]);"
        match = re.search(pattern2, html, re.DOTALL)

    if not match:
        return []

    json_str = match.group(1)

    # Unescape any escaped characters
    json_str = json_str.replace("\\'", "'")
    json_str = json_str.replace('\\"', '"')

    try:
        data = json.loads(json_str)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError as e:
        print(f"[{CINEMA_NAME}] JSON decode error: {e}", file=sys.stderr)

    return []


def _fetch_schedule_html(session: requests.Session) -> tuple:
    """Fetch schedule HTML, trying fallback host if needed."""
    last_error = None
    for base_url, schedule_url in SCHEDULE_URLS:
        try:
            resp = session.get(schedule_url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.text, base_url
        except requests.RequestException as e:
            last_error = e
            print(f"[{CINEMA_NAME}] Request failed for {schedule_url}: {e}", file=sys.stderr)

    if last_error:
        raise last_error
    raise RuntimeError("No schedule URL configured")


def scrape_close_up() -> List[Dict]:
    """
    Scrape Close-Up Film Centre showtimes from their film programmes page.

    The page embeds show data in a JavaScript variable `var shows = '[...]'`
    with JSON containing: id, fp_id, title, blink, show_time, status,
    booking_availability, film_url

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - booking_url: str
    - director, year, country, runtime_min, synopsis: str (optional)
    """
    shows = []

    try:
        session = requests.Session()
        session.trust_env = False  # Ignore env proxy settings for this target
        html, base_url = _fetch_schedule_html(session)

        # Extract JSON data from JavaScript variable
        shows_data = _extract_shows_json(html)
        print(f"[{CINEMA_NAME}] Found {len(shows_data)} show entries in JSON", file=sys.stderr)

        if not shows_data:
            print(f"[{CINEMA_NAME}] Warning: Could not extract shows JSON from page", file=sys.stderr)
            return []

        for entry in shows_data:
            title = _clean(entry.get("title", ""))
            if not title:
                continue

            show_time_str = entry.get("show_time", "")
            parsed = _parse_show_datetime(show_time_str)
            if not parsed:
                continue

            show_date, time_str = parsed

            # Check if within our date window
            if not (TODAY <= show_date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                continue

            # Build detail page URL
            film_url = entry.get("film_url", "")
            detail_url = urljoin(base_url, film_url) if film_url else ""

            # Get booking URL
            booking_url = entry.get("blink", "")

            shows.append({
                "cinema_name": CINEMA_NAME,
                "movie_title": title,
                "movie_title_en": title,
                "date_text": show_date.isoformat(),
                "showtime": time_str,
                "detail_page_url": detail_url,
                "booking_url": booking_url,
                "director": "",
                "year": "",
                "country": "",
                "runtime_min": "",
                "synopsis": "",
            })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings within date window", file=sys.stderr)

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
    data = scrape_close_up()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
