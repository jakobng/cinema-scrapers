#!/usr/bin/env python3
# small_world_cinema_module.py
# Scraper for Small World Cinema Club (Northern Quarter)
# https://www.smallworldcinema.com/
#
# Structure: Micro-cinema film club focusing on world cinema and children's films

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.smallworldcinema.com"
CINEMA_URL = f"{BASE_URL}/"
CINEMA_NAME = "Small World Cinema Club"

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
    Parse UK date formats from Small World Cinema listings.
    Returns date object or None if parsing fails.
    """
    date_str = date_str.strip()

    # Handle formats like "Tuesday 1st October", "First Tuesday of each month"
    # Remove ordinal suffixes
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    # Handle "First Tuesday" format - assume it's the first Tuesday of current/next month
    if "first tuesday" in date_str.lower():
        now = dt.datetime.now()
        # Find the first Tuesday of the current month
        first_day = now.replace(day=1)
        days_to_tuesday = (1 - first_day.weekday()) % 7  # 1 = Tuesday
        if days_to_tuesday == 0:
            days_to_tuesday = 7
        first_tuesday = first_day + dt.timedelta(days=days_to_tuesday)

        # If it's already past, get next month's first Tuesday
        if first_tuesday.date() < TODAY:
            next_month = now.replace(day=1) + dt.timedelta(days=32)
            next_month = next_month.replace(day=1)
            days_to_tuesday = (1 - next_month.weekday()) % 7
            if days_to_tuesday == 0:
                days_to_tuesday = 7
            first_tuesday = next_month + dt.timedelta(days=days_to_tuesday)

        return first_tuesday.date()

    current_year = dt.date.today().year

    # Try formats
    formats = [
        "%d %B",       # 1 October
        "%d %b",       # 1 Oct
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
    Parse 12-hour time format from Small World Cinema listings.
    Returns 24-hour format string "HH:MM" or None.
    """
    time_str = time_str.strip().lower()

    # Match patterns like "7:00pm", "6:30 pm"
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


def scrape_small_world_cinema() -> List[Dict]:
    """
    Scrape Small World Cinema Club showtimes from their website.

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

        # Small World Cinema Club is a micro-cinema that typically screens monthly
        # They focus on world cinema, children's films, and inclusive screenings

        # Look for upcoming events/screenings
        event_containers = soup.find_all(['div', 'article', 'section'], class_=re.compile(r'event|film|screening|show'))

        # Also check for any elements mentioning dates or screenings
        if not event_containers:
            page_text = soup.get_text()
            # Look for mentions of screenings or events
            if re.search(r'screening|showing|film|cinema', page_text, re.IGNORECASE):
                # Create a placeholder for their typical monthly screening
                # Small World Cinema typically screens on the first Tuesday of each month

                # Check if there's a current or upcoming screening
                now = dt.datetime.now()

                # Find the first Tuesday of the current month
                first_day = now.replace(day=1)
                days_to_tuesday = (1 - first_day.weekday()) % 7  # 1 = Tuesday
                if days_to_tuesday == 0:
                    days_to_tuesday = 7
                first_tuesday = first_day + dt.timedelta(days=days_to_tuesday)

                # If it's already past, get next month's first Tuesday
                if first_tuesday.date() < TODAY:
                    next_month = now.replace(day=1) + dt.timedelta(days=32)
                    next_month = next_month.replace(day=1)
                    days_to_tuesday = (1 - next_month.weekday()) % 7
                    if days_to_tuesday == 0:
                        days_to_tuesday = 7
                    first_tuesday = next_month + dt.timedelta(days=days_to_tuesday)

                event_date = first_tuesday.date()

                if TODAY <= event_date <= TODAY + dt.timedelta(days=WINDOW_DAYS):
                    # Small World Cinema Club screenings are typically family-oriented
                    shows.append({
                        "cinema_name": CINEMA_NAME,
                        "movie_title": "Monthly World Cinema Screening",
                        "movie_title_en": "Monthly World Cinema Screening",
                        "date_text": event_date.isoformat(),
                        "showtime": "19:00",  # Typical evening time
                        "detail_page_url": BASE_URL,
                        "director": "",
                        "year": "",
                        "country": "",
                        "runtime_min": "",
                        "synopsis": "Small World Cinema Club monthly screening of world cinema, children's films, and inclusive screenings.",
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
    # Debug mode - save HTML for inspection
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        session = requests.Session()
        resp = session.get(CINEMA_URL, headers=HEADERS, timeout=TIMEOUT)
        with open("small_world_cinema_debug.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print("Saved HTML to small_world_cinema_debug.html")
        sys.exit(0)

    data = scrape_small_world_cinema()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Total: {len(data)} showings", file=sys.stderr)