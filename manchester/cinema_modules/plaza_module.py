#!/usr/bin/env python3
# plaza_module.py
# Scraper for The Plaza cinema (1932 art deco in Stockport)
# https://stockportplaza.co.uk/
#
# Structure: Historic venue with theatre and film screenings

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://stockportplaza.co.uk"
WHATSON_URL = f"{BASE_URL}/whats-on/"
CINEMA_NAME = "The Plaza"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30

TODAY = dt.date.today()
WINDOW_DAYS = 14  # Look ahead 2 weeks


def _clean(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_uk_date(date_str: str) -> Optional[dt.date]:
    """
    Parse UK date formats from Plaza listings.
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Handle formats like "Friday 22nd November", "Saturday 23rd November"
    # Remove ordinal suffixes
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    # Remove day name if present
    date_str = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+",
        "",
        date_str,
        flags=re.IGNORECASE
    )

    current_year = dt.date.today().year

    # Try formats
    formats = [
        "%d %B",       # 22 November
        "%d %b",       # 22 Nov
    ]

    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(date_str.strip(), fmt)
            parsed = parsed.replace(year=current_year)
            # If date is in the past, assume next year
            if parsed.date() < TODAY - dt.timedelta(days=30):
                parsed = parsed.replace(year=current_year + 1)
            return parsed.date()
        except ValueError:
            continue

    return None


def _parse_time_12h(time_str: str) -> Optional[str]:
    """
    Parse 12-hour time format from Plaza listings.
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match patterns like "2:30pm", "7:45 pm", "12:15am"
    match = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    return None


def _extract_event_info(event_element) -> Optional[Dict]:
    """
    Extract event information from a Plaza event listing element.
    Returns dict with title, description, date, time, etc.
    """
    try:
        # Find title - specifically look for p.title
        title_elem = event_element.find('p', class_='title')
        if not title_elem:
            return None

        title = _clean(title_elem.get_text())

        # Only include film events - check for film category in the filterRow
        filter_row = event_element.find('div', class_='filterRow')
        is_film = False
        if filter_row:
            film_link = filter_row.find('a', href=re.compile(r'/whats-on/type/film'))
            if film_link:
                is_film = True

        if not is_film:
            return None

        # Find date/time text - specifically look for p.date
        date_time_text = ""
        date_elem = event_element.find('p', class_='date')
        if date_elem:
            date_time_text = _clean(date_elem.get_text())

        # Extract time from date text (format: "Wednesday 21st and Thursday 22nd January at 7.30pm")
        showtime = ""
        time_match = re.search(r'at\s+(\d{1,2}(?:\.\d{2})?\s*(?:am|pm))', date_time_text, re.IGNORECASE)
        if time_match:
            showtime = time_match.group(1)

        # Find detail page URL - the title link
        detail_url = ""
        title_link = title_elem.find('a')
        if title_link:
            detail_url = urljoin(BASE_URL, title_link.get('href', ''))

        # Get description from the element text
        description = date_time_text  # Use date info as description

        return {
            'title': title,
            'description': description,
            'date_time_text': date_time_text,
            'showtime': showtime,
            'detail_page_url': detail_url,
        }

    except Exception as e:
        print(f"Error extracting event info: {e}", file=sys.stderr)
        return None


def scrape_plaza() -> List[Dict]:
    """
    Scrape The Plaza cinema showtimes from their website.

    Returns a list of showtime records with standard schema:
    - cinema_name: str
    - movie_title: str
    - date_text: str (YYYY-MM-DD)
    - showtime: str (HH:MM)
    - detail_page_url: str
    - director: str (if available)
    - year: str (if available)
    - country: str (if available)
    - runtime_min: str (if available)
    - synopsis: str

    Note: Director, year, runtime etc. are populated by TMDB enrichment in main_scraper.py
    """
    shows = []

    try:
        session = requests.Session()
        resp = session.get(WHATSON_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find event/film listings - specifically look for div.event.box-shadow
        event_containers = soup.find_all('div', class_='event box-shadow')

        print(f"[{CINEMA_NAME}] Found {len(event_containers)} event containers", file=sys.stderr)

        for container in event_containers:
            # Extract event info
            event_info = _extract_event_info(container)
            if not event_info:
                continue

            # Parse dates from the date_time_text
            # Format: "Wednesday 21st and Thursday 22nd January at 7.30pm"
            date_time_text = event_info['date_time_text']
            event_dates = []

            # Extract all date patterns from the text
            date_patterns = [
                r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))',
                r'((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))'
            ]

            for pattern in date_patterns:
                matches = re.findall(pattern, date_time_text, re.IGNORECASE)
                for match in matches:
                    parsed_date = _parse_uk_date(match)
                    if parsed_date and parsed_date not in event_dates:
                        event_dates.append(parsed_date)

            # If no dates found, default to today
            if not event_dates:
                event_dates = [TODAY]

            # Parse showtime
            showtime_parsed = ""
            if event_info['showtime']:
                showtime_parsed = _parse_time_12h(event_info['showtime'])

            # Create showings for each date
            if event_dates and showtime_parsed:
                for event_date in event_dates:
                    # Check if within our date window
                    if TODAY <= event_date <= TODAY + dt.timedelta(days=WINDOW_DAYS):
                        shows.append({
                            "cinema_name": CINEMA_NAME,
                            "movie_title": event_info['title'],
                            "movie_title_en": event_info['title'],  # Will be populated by TMDB
                            "date_text": event_date.isoformat(),
                            "showtime": showtime_parsed,
                            "detail_page_url": event_info['detail_page_url'],
                            "director": "",  # Will be populated by TMDB
                            "year": "",      # Will be populated by TMDB
                            "country": "",   # Will be populated by TMDB
                            "runtime_min": "",  # Will be populated by TMDB
                            "synopsis": event_info['description'],
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
    data = scrape_plaza()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)