#!/usr/bin/env python3
# arthouse_crouch_end_module.py
# Scraper for ArtHouse Crouch End Cinema
# https://www.arthousecrouchend.co.uk/
#
# Structure: Calendar page contains a JavaScript object 'crouchendData' with
# date keys (DD-MM-YYYY) mapping to HTML snippets containing film titles,
# showtimes, and programme IDs.

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.arthousecrouchend.co.uk"
CALENDAR_URL = f"{BASE_URL}/calendar/"
CINEMA_NAME = "ArtHouse Crouch End"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14


def _clean(text: str) -> str:
    """Clean whitespace, decode HTML entities, and normalize text."""
    if not text:
        return ""
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text.strip())


def _parse_date_key(date_key: str) -> Optional[dt.date]:
    """
    Parse date from calendar key format MM-DD-YYYY.
    (Note: Despite appearing European, the site uses US date format)
    """
    if not date_key:
        return None

    # Try MM-DD-YYYY format (US format used by the site)
    try:
        return dt.datetime.strptime(date_key, "%m-%d-%Y").date()
    except ValueError:
        pass

    # Fallback to DD-MM-YYYY format
    try:
        return dt.datetime.strptime(date_key, "%d-%m-%Y").date()
    except ValueError:
        return None


def _parse_time(time_str: str) -> Optional[str]:
    """
    Parse time string to HH:MM format.
    Handles formats like "12:15", "20:30", etc.
    """
    if not time_str:
        return None

    time_str = time_str.strip()

    # Handle HH:MM format
    match = re.match(r"(\d{1,2}):(\d{2})", time_str)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return f"{hours:02d}:{minutes:02d}"

    return None


def _extract_calendar_data(html_content: str) -> dict:
    """
    Extract the crouchendData JavaScript object from the page HTML.
    The object contains date keys mapping to HTML content snippets.
    """
    data = {}

    # Find the start of crouchendData
    start_marker = "crouchendData"
    start_idx = html_content.find(start_marker)
    if start_idx == -1:
        return {}

    # Find the opening brace
    brace_idx = html_content.find("{", start_idx)
    if brace_idx == -1:
        return {}

    # Find matching closing brace
    brace_count = 0
    end_idx = brace_idx
    for i in range(brace_idx, len(html_content)):
        if html_content[i] == "{":
            brace_count += 1
        elif html_content[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break

    js_object = html_content[brace_idx:end_idx]

    # Split by date keys to extract each entry
    # The format is: 'MM-DD-YYYY' : '...'
    parts = re.split(r"'(\d{2}-\d{2}-\d{4})'\s*:", js_object)

    # First part is before any date, then alternating: date, value, date, value...
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            date_key = parts[i]
            value_raw = parts[i + 1].strip()

            # Value is wrapped in single quotes
            if value_raw.startswith("'"):
                # Find the end of the value (closing quote before comma or end)
                # Need to handle nested quotes carefully
                end = -1
                in_quote = True
                for j in range(1, len(value_raw)):
                    if value_raw[j] == "'" and (j + 1 >= len(value_raw) or value_raw[j + 1] in ",}"):
                        end = j
                        break

                if end > 0:
                    html_value = value_raw[1:end]
                    data[date_key] = html_value

    return data


def _extract_films_from_html_snippet(html_snippet: str, date: dt.date) -> List[Dict]:
    """
    Parse the HTML snippet for a specific date to extract films and showtimes.

    The HTML structure (note: often malformed):
    <a class="Film" href="/arthousecrouchend/programme/?programme_id=9821417 " <span ... title="Film: Hamnet ( 12:15 15:00 17:45 20:30 )">Hamnet</span> </a>

    The showtimes are in the title attribute of the span element.
    We use regex because the HTML is often malformed (missing > after href attribute).
    """
    films = []

    if not html_snippet:
        return films

    # Use regex to extract film information from the malformed HTML
    # Pattern to match: href containing programme_id, followed by title attr with times, and film name in span
    # The HTML has pattern like: href="/arthousecrouchend/programme/?programme_id=XXXX " <span ... title="Film: NAME ( TIMES )">NAME</span>

    # Pattern to extract each film entry
    film_pattern = r'href="([^"]*programme_id=\d+[^"]*)"[^>]*<span[^>]*title="([^"]*)"[^>]*>([^<]+)</span>'

    for match in re.finditer(film_pattern, html_snippet, re.IGNORECASE):
        href = match.group(1).strip()
        title_attr = match.group(2)
        film_name = _clean(match.group(3))

        if not film_name:
            continue

        # Build full URL
        if href.startswith("/"):
            detail_url = urljoin(BASE_URL, href)
        else:
            detail_url = href

        # Extract times from the title attribute
        # Format: "Film: Hamnet ( 12:15 15:00 17:45 20:30 )"
        time_pattern = r'\b(\d{1,2}:\d{2})\b'
        times = re.findall(time_pattern, title_attr)

        # Create entries for each showtime
        for time_str in times:
            parsed_time = _parse_time(time_str)
            if parsed_time:
                films.append({
                    "title": film_name,
                    "time": parsed_time,
                    "detail_url": detail_url,
                })

    return films


def _extract_films_from_raw_pattern(html_content: str) -> List[Dict]:
    """
    Alternative extraction method that parses the raw JavaScript object
    using regex patterns when JSON parsing fails.
    """
    films = []

    # Pattern to match date entries in the crouchendData object
    # Looking for "DD-MM-YYYY": "..." patterns
    date_pattern = r'"(\d{2}-\d{2}-\d{4})"\s*:\s*"([^"]*(?:\\.[^"]*)*)"'

    for match in re.finditer(date_pattern, html_content):
        date_key = match.group(1)
        html_snippet = match.group(2)

        # Unescape the HTML snippet
        html_snippet = html_snippet.encode().decode('unicode_escape')
        html_snippet = html.unescape(html_snippet)

        date = _parse_date_key(date_key)
        if not date:
            continue

        # Check if within window
        if not (TODAY <= date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
            continue

        # Extract films from this date's HTML snippet
        date_films = _extract_films_from_html_snippet(html_snippet, date)

        for film in date_films:
            films.append({
                "date": date,
                **film
            })

    return films


def scrape_arthouse_crouch_end() -> List[Dict]:
    """
    Scrape ArtHouse Crouch End showtimes from the calendar page.

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
        resp = session.get(CALENDAR_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        html_content = resp.text

        # Try to extract calendar data as JSON first
        calendar_data = _extract_calendar_data(html_content)

        if calendar_data:
            # Process each date in the calendar data
            for date_key, html_snippet in calendar_data.items():
                date = _parse_date_key(date_key)
                if not date:
                    continue

                # Check if within window
                if not (TODAY <= date < TODAY + dt.timedelta(days=WINDOW_DAYS)):
                    continue

                # Decode the HTML snippet if it's escaped
                if isinstance(html_snippet, str):
                    html_snippet = html.unescape(html_snippet)

                # Extract films from this date's HTML snippet
                date_films = _extract_films_from_html_snippet(html_snippet, date)

                for film in date_films:
                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": film["title"],
                        "movie_title_en": film["title"],
                        "date_text": date.isoformat(),
                        "showtime": film["time"],
                        "detail_page_url": film["detail_url"],
                        "booking_url": film["detail_url"],  # Same page for booking
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "",
                        "format_tags": [],
                    })
        else:
            # Fallback: try regex-based extraction
            print(f"[{CINEMA_NAME}] JSON parsing failed, using regex fallback", file=sys.stderr)
            films = _extract_films_from_raw_pattern(html_content)

            for film in films:
                shows.append({
                    "cinema_name": CINEMA_NAME,
                    "movie_title": film["title"],
                    "movie_title_en": film["title"],
                    "date_text": film["date"].isoformat(),
                    "showtime": film["time"],
                    "detail_page_url": film["detail_url"],
                    "booking_url": film["detail_url"],
                    "director": "",
                    "year": "",
                    "country": "",
                    "runtime_min": "",
                    "synopsis": "",
                    "format_tags": [],
                })

        print(f"[{CINEMA_NAME}] Found {len(shows)} showings", file=sys.stderr)

    except requests.RequestException as e:
        print(f"[{CINEMA_NAME}] HTTP Error: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[{CINEMA_NAME}] Error: {e}", file=sys.stderr)
        raise

    # Deduplicate by (title, date, showtime)
    seen = set()
    unique_shows = []
    for s in shows:
        key = (s["movie_title"], s["date_text"], s["showtime"])
        if key not in seen:
            seen.add(key)
            unique_shows.append(s)

    return sorted(unique_shows, key=lambda x: (x["date_text"], x["showtime"], x["movie_title"]))


if __name__ == "__main__":
    data = scrape_arthouse_crouch_end()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)
