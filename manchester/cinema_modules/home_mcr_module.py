#!/usr/bin/env python3
# home_mcr_module.py
# Scraper for HOME Manchester (BFI-affiliated, 5 screens)
# https://homemcr.org/cinema/
#
# Structure: Modern website with film listings showing day-by-day showtimes

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://homemcr.org"
CINEMA_URL = f"{BASE_URL}/cinema/"
CINEMA_NAME = "HOME Manchester"

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
    Parse UK date formats from HOME listings like "Sunday 23 Nov", "Monday 24 Nov".
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

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
        "%d %b",       # 23 Nov
        "%d %B",       # 23 November
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
    Parse time format from HOME listings.
    Handles both 12-hour format ("2:00pm") and 24-hour format ("14:00").
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # First try 12-hour format with am/pm
    match_12h = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)", time_str)
    if match_12h:
        hour = int(match_12h.group(1))
        minute = int(match_12h.group(2))
        period = match_12h.group(3)

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute:02d}"

    # Then try 24-hour format
    match_24h = re.match(r"(\d{1,2}):(\d{2})", time_str)
    if match_24h:
        hour = int(match_24h.group(1))
        minute = int(match_24h.group(2))

        # Validate hour range
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return None




def scrape_home_mcr() -> List[Dict]:
    """
    Scrape HOME Manchester showtimes from their cinema listings page.

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
        resp = session.get(CINEMA_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find all movie entries - HOME uses movie-card structure
        movie_entries = soup.find_all('li', class_='movie-card')

        print(f"[{CINEMA_NAME}] Found {len(movie_entries)} movie entries", file=sys.stderr)

        # Extract all movie information first
        movies_info = []
        for movie_entry in movie_entries:
            movie_info = _extract_movie_info(movie_entry)
            if movie_info:
                movies_info.append((movie_entry, movie_info))

        # Now parse showtimes from the entire page
        # HOME Manchester seems to have showtimes in a separate section
        page_text = _clean(soup.get_text())

        # Look for showtime patterns and associate them with movies
        for movie_entry, movie_info in movies_info:
            movie_shows = _parse_showtimes_from_page(movie_entry, movie_info)
            shows.extend(movie_shows)

        print(f"[{CINEMA_NAME}] Found {len(shows)} total showings", file=sys.stderr)

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


def _extract_movie_info(movie_element) -> Optional[Dict]:
    """Extract movie information from a movie entry element."""
    try:
        # Find the title element
        title_elem = movie_element.find('h4', class_='title')
        if not title_elem:
            return None

        title_text = _clean(title_elem.get_text())

        # Extract title and certificate
        title_match = re.match(r'(.+?)\s*\((\d{1,2}[A-Z]?)\)', title_text)
        if title_match:
            title = title_match.group(1).strip()
            certificate = title_match.group(2)
        else:
            title = title_text
            certificate = ""

        # Find description (subtitle)
        description = ""
        subtitle_elem = movie_element.find('div', class_='subtitle')
        if subtitle_elem:
            description = _clean(subtitle_elem.get_text())

        # Find duration
        runtime_min = ""
        duration_elem = movie_element.find('div', class_='duration')
        if duration_elem:
            duration_text = _clean(duration_elem.get_text())
            duration_match = re.search(r'(\d+)\s*min', duration_text)
            if duration_match:
                runtime_min = duration_match.group(1)

        # Find detail URL
        detail_url = ""
        title_link = movie_element.find('a')
        if title_link:
            detail_url = urljoin(BASE_URL, title_link.get('href', ''))

        return {
            'title': title,
            'description': description,
            'runtime_min': runtime_min,
            'detail_page_url': detail_url,
        }

    except Exception as e:
        print(f"Error extracting movie info: {e}", file=sys.stderr)
        return None


def _parse_showtimes_from_page(movie_element, movie_info: Dict) -> List[Dict]:
    """Parse showtimes from a movie element."""
    shows = []

    try:
        # Find all day entries within this movie
        day_entries = movie_element.find_all('li', class_='day')

        for day_entry in day_entries:
            # Get the date from the data-date attribute
            date_attr = day_entry.get('data-date')
            if date_attr:
                try:
                    current_date = dt.date.fromisoformat(date_attr)
                except ValueError:
                    continue
            else:
                continue

            # Find all show buttons within this day
            show_buttons = day_entry.find_all('a', class_=re.compile(r'btn.*btn-order'))

            for button in show_buttons:
                # Get the button text and extract time from the beginning
                button_text = _clean(button.get_text())

                # Time is at the beginning of the button text (e.g., "12:45 Tickets AD")
                time_match = re.match(r'(\d{1,2}:\d{2})', button_text)
                if time_match:
                    time_text = time_match.group(1)
                    parsed_time = _parse_time_12h(time_text)

                    if parsed_time:
                        # Check if this is available (not sold out, not past)
                        button_classes = button.get('class', [])
                        if ('btn-active' in button_classes or
                            'status-normaal' in button_classes):

                            # Skip past events
                            if 'past' in _clean(button.get_text()).lower():
                                continue

                            shows.append({
                                "cinema_name": CINEMA_NAME,
                                "movie_title": movie_info['title'],
                                "movie_title_en": movie_info['title'],
                                "date_text": current_date.isoformat(),
                                "showtime": parsed_time,
                                "detail_page_url": movie_info['detail_page_url'],
                                "director": "",
                                "year": "",
                                "country": "",
                                "runtime_min": movie_info['runtime_min'],
                                "synopsis": movie_info['description'],
                            })

    except Exception as e:
        print(f"Error parsing showtimes: {e}", file=sys.stderr)

    return shows


if __name__ == "__main__":

    data = scrape_home_mcr()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)